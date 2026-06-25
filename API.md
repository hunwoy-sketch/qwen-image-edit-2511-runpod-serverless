# Qwen-Image-Edit-2511 Rapid-AIO —— API 说明

基于 RunPod Serverless 的 ComfyUI 图片编辑接口。支持两种调用模式：

- **内置模式**：使用内置的 Qwen-Rapid-AIO 工作流，只需传 `prompt` + 图片等便捷参数。
- **通用模式**：直接传入任意 ComfyUI **API 格式**工作流，一个端点跑多种工作流。

> 判定规则：`input` 里只要带了 `workflow` 字段，就走通用模式；否则走内置模式。

---

## 1. 基础信息

| 项 | 值 |
| --- | --- |
| Base URL | `https://api.runpod.ai/v2/{ENDPOINT_ID}` |
| 鉴权 | 请求头 `Authorization: Bearer {RUNPOD_API_KEY}` |
| Content-Type | `application/json` |
| 请求体 | `{ "input": { ... } }` |

`{ENDPOINT_ID}` 为你的 Serverless 端点 ID，`{RUNPOD_API_KEY}` 在 RunPod 控制台 Settings → API Keys 获取。

---

## 2. 调用接口

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/runsync` | POST | 同步调用，等待并直接返回结果。适合调试、单张快速出图 |
| `/run` | POST | 异步调用，立即返回任务 `id`，再轮询 `/status` 取结果。适合耗时任务、首次冷启动 |
| `/status/{id}` | GET | 查询异步任务状态与结果 |
| `/cancel/{id}` | POST | 取消任务 |
| `/health` | GET | 查看端点 worker 状态 |

**建议**：首次调用会冷启动（拉起容器 + 从 Network Volume 加载约 28GB 主模型，可能 1～3 分钟），优先用 `/run` + 轮询，避免 `/runsync` 客户端超时。

任务状态：`IN_QUEUE` → `IN_PROGRESS` → `COMPLETED` / `FAILED`。

---

## 3. 内置模式参数

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `prompt` | string | 是 | — | 编辑提示词 |
| `image_path` / `image_url` / `image_base64` | string | 是 | — | 第 1 张图（路径 / URL / Base64 三选一） |
| `image_path_2` / `image_url_2` / `image_base64_2` | string | 否 | — | 第 2 张图 |
| `image_path_3` / `image_url_3` / `image_base64_3` | string | 否 | — | 第 3 张图 |
| `negative_prompt` | string | 否 | "" | 负向提示词 |
| `seed` | int | 否 | 65454653 | 随机种子 |
| `steps` | int | 否 | 4 | 采样步数 |
| `cfg` | float | 否 | 1 | CFG |
| `sampler_name` | string | 否 | sa_solver | 采样器 |
| `scheduler` | string | 否 | beta | 调度器 |
| `denoise` | float | 否 | 1 | 去噪强度 |
| `width` / `height` | int | 否 | 768 | 输出尺寸 |
| `batch_size` | int | 否 | 1 | 批量数量 |
| `checkpoint` | string | 否 | 工作流内置 | 覆盖主模型文件名 |
| `loras` | array | 否 | qwen_MCNL 开启 | LoRA 列表，见 3.1 |
| `lora` + `lora_strength` | string + float | 否 | — | 便捷写法：单个 LoRA |

`image_base64` 兼容 `data:image/png;base64,` 前缀。

### 3.1 `loras` 数组

```json
{ "on": true, "lora": "qwen_MCNL_v1.0.safetensors", "strength": 1.0, "strengthTwo": null }
```

可用 LoRA（需先放进 Network Volume 的 `loras/`）：

- `qwen_MCNL_v1.0.safetensors`（默认开启）
- `Qwen4Play-2512.1_e10.safetensors`
- `Meta4.safetensors`
- `bfs_v2_head_000007000.safetensors`
- `GiorgioV_Qwen4Play-2512.1_e10.safetensors`
- `qwen_image_edit_remove-clothing_v1.0.safetensors`
- `Qwen-Image-Edit-2511-Object-Remover-v2-9200.safetensors`
- `qe2511_consis_alpha_patched.safetensors`
- `Qwen4Play_v2.safetensors`

### 3.2 内置模式返回

```json
{ "image": "<base64 png>" }
```

---

## 4. 通用模式参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `workflow` | object / string | 是 | 完整的 ComfyUI **API 格式**工作流（节点 ID → 节点）。在 ComfyUI 界面用 `Workflow → Export (API)` 导出；传字符串时须为合法 JSON |
| `images` | array | 否 | 输入图数组，见 4.1。`name` 要与工作流里 `LoadImage` 节点填的文件名一致 |
| `output_node` | string | 否 | 只返回指定节点 ID 的输出图；不填则返回全部输出节点 |

### 4.1 `images` 数组

每个元素三选一提供图源，`name` 为该图在 ComfyUI `input/` 下的文件名：

```json
{ "name": "input.png", "image_url": "https://example.com/a.jpg" }
{ "name": "ref.png",   "image_base64": "...." }
{ "name": "mask.png",  "image_path": "/runpod-volume/xxx.png" }
```

### 4.2 通用模式返回

```json
{
  "images": [
    { "node_id": "6", "image": "<base64 png>" }
  ],
  "image": "<base64 png>",
  "saved_inputs": ["input.png"]
}
```

- `images`：所有输出节点的图片列表。
- `image`：便捷字段，等于 `images[0].image`。
- `saved_inputs`：本次实际落地的输入图文件名。

### 4.3 使用前提

1. 工作流用到的自定义节点必须已装进镜像（当前：ComfyUI-Manager、rgthree-comfy）。缺节点会校验失败，需在 `Dockerfile` 里 `git clone` 补装。
2. 工作流引用的 checkpoint / LoRA 必须已在 Network Volume 中。
3. 节点 ID、`class_type`、`inputs` 必须完整（务必用 ComfyUI 的 **Export (API)**，而非普通保存的界面版 JSON）。

---

## 5. 错误返回

业务错误统一以 `output.error` 返回（HTTP 仍为 200）：

```json
{ "status": "COMPLETED", "output": { "error": "至少需要 1 张输入图片（image_path / image_url / image_base64 之一）" } }
```

常见错误：

| 错误信息（节选） | 原因 | 处理 |
| --- | --- | --- |
| `至少需要 1 张输入图片` | 内置模式没传图 | 带上 `image_url` / `image_base64` / `image_path` |
| `ComfyUI 拒绝工作流 (HTTP 400): ... Value not in list: ckpt_name ... not in []` | 模型不在卷上 / 卷未挂载 | 把模型下到 `/runpod-volume/checkpoints`，并给端点绑定该卷 |
| `ComfyUI 拒绝工作流 (HTTP 400): ... <节点名> ...` | 工作流用到未安装的节点 | 在 `Dockerfile` 补装该自定义节点后重建镜像 |
| `workflow 不是合法 JSON` | 通用模式 `workflow` 字符串非法 | 检查 JSON 格式 |
| `工作流执行完成但没有图片输出` | 工作流没有产图节点 / 输出被忽略 | 确认有 SaveImage 等输出节点，或检查 `output_node` |

RunPod 平台级错误（鉴权失败、端点不存在等）则以 HTTP 4xx/5xx 返回，请检查 API Key 与 Endpoint ID。

---

## 6. 调用示例

### 6.1 curl —— 内置模式（同步）

```bash
API_KEY="你的_RUNPOD_API_KEY"
ENDPOINT="你的_ENDPOINT_ID"

curl -s -X POST "https://api.runpod.ai/v2/$ENDPOINT/runsync" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
        "input": {
          "prompt": "make it anime style",
          "image_url": "https://picsum.photos/768",
          "steps": 4,
          "width": 768,
          "height": 768
        }
      }' \
  | python3 -c "import sys,json,base64; d=json.load(sys.stdin); open('out.png','wb').write(base64.b64decode(d['output']['image'])); print('已保存 out.png')"
```

### 6.2 curl —— 通用模式（异步 + 轮询）

```bash
# 1) 提交（workflow 为完整 API 格式工作流）
JOB=$(curl -s -X POST "https://api.runpod.ai/v2/$ENDPOINT/run" \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d @example_request_workflow.json)
ID=$(echo "$JOB" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "job id: $ID"

# 2) 轮询
curl -s "https://api.runpod.ai/v2/$ENDPOINT/status/$ID" \
  -H "Authorization: Bearer $API_KEY"
```

### 6.3 Python

```python
import requests, base64

API_KEY = "你的_RUNPOD_API_KEY"
ENDPOINT = "你的_ENDPOINT_ID"
BASE = f"https://api.runpod.ai/v2/{ENDPOINT}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# 内置模式
payload = {"input": {"prompt": "remove background", "image_url": "https://picsum.photos/768", "steps": 4}}
r = requests.post(f"{BASE}/runsync", json=payload, headers=HEADERS, timeout=300).json()
out = r["output"]
if "error" in out:
    raise RuntimeError(out["error"])
open("out.png", "wb").write(base64.b64decode(out["image"]))
```

### 6.4 仓库自带测试脚本

```bash
cp .env.example test.env   # 填 RUNPOD_API_KEY 与 RUNPOD_ENDPOINT_ID

# 内置模式
python test_api.py --mode url --image-url "https://picsum.photos/768" --prompt "make it anime"

# 通用模式
python test_api.py --json example_request_workflow.json
python test_api.py --workflow workflow/qwen_rapid_aio_api.json \
  --image-url "https://example.com/ref.jpg" --image-name input.png --output-node 6
```

---

## 7. 备注

- 输出图为 Base64 编码的 PNG，需自行解码保存。
- 临时输出写在容器 `/tmp`，任务结束即丢弃，不持久化。
- 改动 `handler.py` 后需**重新构建镜像并重新部署端点**才生效。
