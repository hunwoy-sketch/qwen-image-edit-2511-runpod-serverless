import runpod
import os
import websocket
import base64
import json
import uuid
import logging
import urllib.request
import urllib.parse
import urllib.error
import binascii
import subprocess
import time
import copy


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CUDA 检查
# ---------------------------------------------------------------------------
def check_cuda_availability():
    """检查 CUDA 是否可用，并设置环境变量。"""
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("✅ CUDA 可用")
            os.environ['CUDA_VISIBLE_DEVICES'] = '0'
            return True
        logger.error("❌ CUDA 不可用")
        raise RuntimeError("需要 CUDA 但当前不可用")
    except Exception as e:
        logger.error(f"❌ CUDA 检查失败: {e}")
        raise RuntimeError(f"CUDA 初始化失败: {e}")


try:
    check_cuda_availability()
except Exception as e:
    logger.error(f"致命错误: {e}")
    exit(1)


# ---------------------------------------------------------------------------
# ComfyUI 连接配置
# ---------------------------------------------------------------------------
server_address = os.getenv('SERVER_ADDRESS', '127.0.0.1')
comfy_port = os.getenv('COMFY_PORT', '8188')
client_id = str(uuid.uuid4())

# ComfyUI 输入目录：LoadImage 节点从这里读取图片
COMFY_INPUT_DIR = os.getenv('COMFY_INPUT_DIR', '/ComfyUI/input')

# 工作流文件
_WORKFLOW_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "workflow",
    "qwen_rapid_aio_api.json",
)

# ---------------------------------------------------------------------------
# 工作流节点 ID 映射（与 qwen_rapid_aio_api.json 一致）
# ---------------------------------------------------------------------------
NODE_CHECKPOINT = "1"
NODE_LORA_LOADER = "10"
NODE_KSAMPLER = "2"
NODE_POSITIVE = "3"
NODE_NEGATIVE = "4"
NODE_VAEDECODE = "5"
NODE_SAVE = "6"
NODE_IMAGE_1 = "7"
NODE_IMAGE_2 = "8"
NODE_IMAGE_3 = "11"
NODE_LATENT = "9"

# 默认 LoRA 配置（与原工作流 Power Lora Loader 一致）
DEFAULT_LORAS = [
    {"on": True,  "lora": "qwen_MCNL_v1.0.safetensors",                               "strength": 1.0},
    {"on": False, "lora": "Qwen4Play-2512.1_e10.safetensors",                         "strength": 1.0},
    {"on": False, "lora": "Meta4.safetensors",                                        "strength": 1.0},
    {"on": False, "lora": "bfs_v2_head_000007000.safetensors",                        "strength": 1.0},
    {"on": False, "lora": "GiorgioV_Qwen4Play-2512.1_e10.safetensors",                "strength": 0.8},
    {"on": False, "lora": "qwen_image_edit_remove-clothing_v1.0.safetensors",         "strength": 1.0},
    {"on": False, "lora": "Qwen-Image-Edit-2511-Object-Remover-v2-9200.safetensors",  "strength": 0.7},
    {"on": False, "lora": "qe2511_consis_alpha_patched.safetensors",                  "strength": 1.0},
    {"on": False, "lora": "Qwen4Play_v2.safetensors",                                 "strength": 1.0},
]


# ---------------------------------------------------------------------------
# ComfyUI HTTP / WebSocket 交互
# ---------------------------------------------------------------------------
def queue_prompt(prompt):
    url = f"http://{server_address}:{comfy_port}/prompt"
    logger.info(f"提交工作流到: {url}")
    payload = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        # ComfyUI 校验失败时会在响应体里给出具体原因（缺模型/缺节点等）
        body = e.read().decode('utf-8', 'ignore')
        logger.error(f"ComfyUI 拒绝工作流 (HTTP {e.code}): {body}")
        raise RuntimeError(f"ComfyUI 拒绝工作流 (HTTP {e.code}): {body}")


def get_image(filename, subfolder, folder_type):
    url = f"http://{server_address}:{comfy_port}/view"
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{url}?{url_values}") as response:
        return response.read()


def get_history(prompt_id):
    url = f"http://{server_address}:{comfy_port}/history/{prompt_id}"
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read())


def get_images(ws, prompt):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break
        else:
            continue

    history = get_history(prompt_id)[prompt_id]
    for node_id in history['outputs']:
        node_output = history['outputs'][node_id]
        images_output = []
        if 'images' in node_output:
            for image in node_output['images']:
                image_data = get_image(image['filename'], image['subfolder'], image['type'])
                if isinstance(image_data, bytes):
                    image_data = base64.b64encode(image_data).decode('utf-8')
                images_output.append(image_data)
        output_images[node_id] = images_output
    return output_images


def load_workflow(workflow_path):
    with open(workflow_path, 'r', encoding='utf-8') as file:
        return json.load(file)


# ---------------------------------------------------------------------------
# 输入处理（path / url / base64）—— 统一落地到 ComfyUI input 目录
# ---------------------------------------------------------------------------
def download_file_from_url(url, output_path):
    result = subprocess.run(
        ['wget', '-O', output_path, '--no-verbose', url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise Exception(f"URL 下载失败: {result.stderr}")
    logger.info(f"✅ 已下载 {url} -> {output_path}")
    return output_path


def save_base64_to_file(base64_data, output_path):
    # 兼容 data:image/png;base64, 前缀
    if isinstance(base64_data, str) and base64_data.startswith('data:'):
        base64_data = base64_data.split(',', 1)[-1]
    try:
        decoded = base64.b64decode(base64_data)
    except (binascii.Error, ValueError) as e:
        raise Exception(f"Base64 解码失败: {e}")
    with open(output_path, 'wb') as f:
        f.write(decoded)
    logger.info(f"✅ Base64 已保存到 {output_path}")
    return output_path


def prepare_input_image(job_input, suffix, index):
    """根据 image_path/image_url/image_base64 准备一张输入图片。

    返回 ComfyUI input 目录下的文件名（供 LoadImage 节点使用），未提供则返回 None。
    """
    path_key = f"image_path{suffix}"
    url_key = f"image_url{suffix}"
    b64_key = f"image_base64{suffix}"

    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    filename = f"input_image_{index}_{uuid.uuid4().hex}.png"
    dest = os.path.abspath(os.path.join(COMFY_INPUT_DIR, filename))

    if path_key in job_input and job_input[path_key]:
        src = job_input[path_key]
        if not os.path.exists(src):
            raise Exception(f"找不到图片路径: {src}")
        # 复制到 input 目录，确保 LoadImage 能按文件名读取
        with open(src, 'rb') as rf, open(dest, 'wb') as wf:
            wf.write(rf.read())
        logger.info(f"📁 已复制路径图片 {src} -> {dest}")
        return filename
    if url_key in job_input and job_input[url_key]:
        download_file_from_url(job_input[url_key], dest)
        return filename
    if b64_key in job_input and job_input[b64_key]:
        save_base64_to_file(job_input[b64_key], dest)
        return filename
    return None


# ---------------------------------------------------------------------------
# LoRA 配置应用到 Power Lora Loader (rgthree) 节点
# ---------------------------------------------------------------------------
def apply_loras(prompt, loras):
    """用 loras 列表重建 Power Lora Loader 节点的 lora_N 输入。

    loras: [{"on": bool, "lora": "xxx.safetensors", "strength": float,
             "strengthTwo": float|None(可选)}]
    """
    node = prompt[NODE_LORA_LOADER]
    inputs = node["inputs"]

    # 移除旧的 lora_N 键，保留 model/clip/header
    for key in [k for k in list(inputs.keys()) if k.lower().startswith("lora_")]:
        del inputs[key]

    for i, item in enumerate(loras, start=1):
        entry = {
            "on": bool(item.get("on", True)),
            "lora": item["lora"],
            "strength": float(item.get("strength", 1.0)),
            "strengthTwo": item.get("strengthTwo", None),
        }
        inputs[f"lora_{i}"] = entry


# ---------------------------------------------------------------------------
# 等待 ComfyUI 就绪
# ---------------------------------------------------------------------------
def wait_for_comfy_http(max_attempts=180):
    http_url = f"http://{server_address}:{comfy_port}/"
    for attempt in range(max_attempts):
        try:
            urllib.request.urlopen(http_url, timeout=5)
            logger.info(f"ComfyUI HTTP 就绪（尝试 {attempt + 1}）")
            return
        except Exception as e:
            logger.warning(f"等待 ComfyUI HTTP（{attempt + 1}/{max_attempts}）: {e}")
            time.sleep(1)
    raise Exception("无法连接 ComfyUI 服务，请确认服务已启动。")


def connect_ws(max_attempts=36):
    ws_url = f"ws://{server_address}:{comfy_port}/ws?clientId={client_id}"
    ws = websocket.WebSocket()
    for attempt in range(max_attempts):
        try:
            ws.connect(ws_url)
            logger.info(f"WebSocket 连接成功（尝试 {attempt + 1}）")
            return ws
        except Exception as e:
            logger.warning(f"WebSocket 连接失败（{attempt + 1}/{max_attempts}）: {e}")
            time.sleep(5)
    raise Exception("WebSocket 连接超时")


# ---------------------------------------------------------------------------
# 通用模式：直接接收 ComfyUI API 格式工作流
# ---------------------------------------------------------------------------
def save_named_images(images):
    """保存 images 数组到 ComfyUI input 目录。

    images: [{"name": "input.png", "image_url"/"image_base64"/"image_path": ...}]
    name 要与工作流里 LoadImage 节点的文件名一致；未给 name 则自动命名。
    返回已保存的文件名列表。
    """
    os.makedirs(COMFY_INPUT_DIR, exist_ok=True)
    saved = []
    for i, item in enumerate(images, start=1):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or f"input_{i}_{uuid.uuid4().hex}.png"
        dest = os.path.abspath(os.path.join(COMFY_INPUT_DIR, name))
        if item.get("image_path"):
            src = item["image_path"]
            if not os.path.exists(src):
                raise Exception(f"找不到图片路径: {src}")
            with open(src, 'rb') as rf, open(dest, 'wb') as wf:
                wf.write(rf.read())
        elif item.get("image_url"):
            download_file_from_url(item["image_url"], dest)
        elif item.get("image_base64"):
            save_base64_to_file(item["image_base64"], dest)
        else:
            logger.warning(f"images[{i}] 未提供 image_url/image_base64/image_path，跳过")
            continue
        saved.append(name)
    return saved


def run_generic_workflow(job_input):
    """通用模式：原样提交客户端传入的 ComfyUI API 工作流。"""
    workflow = job_input["workflow"]
    if isinstance(workflow, str):
        try:
            workflow = json.loads(workflow)
        except json.JSONDecodeError as e:
            return {"error": f"workflow 不是合法 JSON: {e}"}
    if not isinstance(workflow, dict):
        return {"error": "workflow 必须是 ComfyUI API 格式（节点 ID -> 节点 的对象）"}

    # 落地输入图片（供工作流内 LoadImage 节点按文件名读取）
    try:
        saved = save_named_images(job_input.get("images", []) or [])
    except Exception as e:
        return {"error": f"输入图片处理失败: {e}"}

    wait_for_comfy_http()
    ws = connect_ws()
    try:
        outputs = get_images(ws, workflow)
    except RuntimeError as e:
        return {"error": str(e), "saved_inputs": saved}
    finally:
        ws.close()

    # 整理所有输出节点的图片
    result_images = []
    for node_id, imgs in outputs.items():
        for b64 in imgs:
            result_images.append({"node_id": node_id, "image": b64})

    if not result_images:
        return {"error": "工作流执行完成但没有图片输出。", "saved_inputs": saved}

    # 可选：只返回指定节点的输出
    output_node = job_input.get("output_node")
    if output_node is not None:
        filtered = [x for x in result_images if x["node_id"] == str(output_node)]
        if filtered:
            result_images = filtered

    return {
        "images": result_images,            # 全部输出
        "image": result_images[0]["image"],  # 便捷：第一张
        "saved_inputs": saved,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def handler(job):
    job_input = job.get("input", {})
    logger.info(f"收到任务输入键: {list(job_input.keys())}")

    # ---- 通用模式：客户端直接传入 ComfyUI API 工作流，支持任意工作流 ----
    if job_input.get("workflow"):
        return run_generic_workflow(job_input)

    # ---- 兼容模式：使用内置 Qwen-Rapid-AIO 工作流 + 便捷参数 ----
    # ---- 1) 收集 1~3 张输入图片 ----
    image_files = []
    for index, suffix in enumerate(["", "_2", "_3"], start=1):
        fname = prepare_input_image(job_input, suffix, index)
        if fname is None:
            break
        image_files.append(fname)

    num_images = len(image_files)
    if num_images == 0:
        return {"error": "至少需要 1 张输入图片（image_path / image_url / image_base64 之一）"}

    # ---- 2) 加载并填充工作流 ----
    prompt = copy.deepcopy(load_workflow(_WORKFLOW_PATH))

    # 图片节点
    prompt[NODE_IMAGE_1]["inputs"]["image"] = image_files[0]
    if num_images >= 2:
        prompt[NODE_IMAGE_2]["inputs"]["image"] = image_files[1]
    else:
        # 删除未使用的图片节点及其在正向编码器中的引用
        prompt.pop(NODE_IMAGE_2, None)
        prompt[NODE_POSITIVE]["inputs"].pop("image2", None)
    if num_images >= 3:
        prompt[NODE_IMAGE_3]["inputs"]["image"] = image_files[2]
    else:
        prompt.pop(NODE_IMAGE_3, None)
        prompt[NODE_POSITIVE]["inputs"].pop("image3", None)

    # 提示词
    prompt[NODE_POSITIVE]["inputs"]["prompt"] = job_input.get("prompt", "")
    if "negative_prompt" in job_input:
        prompt[NODE_NEGATIVE]["inputs"]["prompt"] = job_input["negative_prompt"]

    # 采样参数
    ksampler = prompt[NODE_KSAMPLER]["inputs"]
    if "seed" in job_input:
        ksampler["seed"] = int(job_input["seed"])
    if "steps" in job_input:
        ksampler["steps"] = int(job_input["steps"])
    if "cfg" in job_input:
        ksampler["cfg"] = float(job_input["cfg"])
    if "sampler_name" in job_input:
        ksampler["sampler_name"] = job_input["sampler_name"]
    if "scheduler" in job_input:
        ksampler["scheduler"] = job_input["scheduler"]
    if "denoise" in job_input:
        ksampler["denoise"] = float(job_input["denoise"])

    # 输出尺寸
    latent = prompt[NODE_LATENT]["inputs"]
    if "width" in job_input:
        latent["width"] = int(job_input["width"])
    if "height" in job_input:
        latent["height"] = int(job_input["height"])
    if "batch_size" in job_input:
        latent["batch_size"] = int(job_input["batch_size"])

    # 主模型 checkpoint（一般无需修改，保留以便覆盖）
    if "checkpoint" in job_input:
        prompt[NODE_CHECKPOINT]["inputs"]["ckpt_name"] = job_input["checkpoint"]

    # LoRA 配置
    if "loras" in job_input and isinstance(job_input["loras"], list) and job_input["loras"]:
        apply_loras(prompt, job_input["loras"])
    elif "lora" in job_input and job_input["lora"]:
        # 便捷写法：单个 lora 文件名 + 可选 lora_strength
        apply_loras(prompt, [{
            "on": True,
            "lora": job_input["lora"],
            "strength": float(job_input.get("lora_strength", 1.0)),
        }])
    # 未指定则使用工作流内置默认（lora_1 = qwen_MCNL 开启）

    # ---- 3) 连接 ComfyUI 并执行 ----
    wait_for_comfy_http()
    ws = connect_ws()
    try:
        images = get_images(ws, prompt)
    except RuntimeError as e:
        return {"error": str(e)}
    finally:
        ws.close()

    if not images:
        return {"error": "未能生成图片。"}

    # 返回 SaveImage 节点输出，回退到任意有图片的节点
    if NODE_SAVE in images and images[NODE_SAVE]:
        return {"image": images[NODE_SAVE][0]}
    for node_id in images:
        if images[node_id]:
            return {"image": images[node_id][0]}

    return {"error": "找不到输出图片。"}


runpod.serverless.start({"handler": handler})
