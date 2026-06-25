# Qwen-Image-Edit-2511 Rapid-AIO · RunPod Serverless

把 ComfyUI 工作流 `Qwen-Rapid-AIO.json` 部署成 RunPod Serverless 端点，通过 HTTP API 做提示词驱动的图片编辑（支持 1~3 张输入图、可切换 LoRA）。

## 架构

按"模型分层放置"原则设计：

| 内容 | 存放位置 | 原因 |
| --- | --- | --- |
| 主模型 `Qwen-Rapid-AIO-NSFW-v23.safetensors`（AIO，含 MODEL/CLIP/VAE，~28GB） | **Network Volume** `/runpod-volume/checkpoints` | 避免烧入镜像导致 RunPod Hub 构建超时（30 分钟上限） |
| LoRA（几百 MB，经常更换） | **Network Volume** `/runpod-volume/loras` | 随时增删，加载稍慢但可接受 |
| 推理临时输出 | **Container Disk 的 `/tmp`** | 用完即丢，无需持久化 |

ComfyUI 通过 `extra_model_paths.yaml` 把 `/runpod-volume` 的 `checkpoints`、`loras` 加入搜索路径，`entrypoint.sh` 再做一次软链兜底。

> 注：早期版本把主模型烧进镜像以加快冷启动，但 RunPod Hub 构建有 30 分钟硬上限，
> 下载 ~28GB 模型会超时失败。现改为放 Network Volume。
> 若你坚持要"烧入镜像 + 快冷启动"，请在本地 `docker build` 后推送镜像（本地构建无时间限制），
> 再把 `setup_network_volume.sh` 里的主模型下载段删掉即可。

## 目录结构

```
runpod-serverless/
├── Dockerfile                  # ComfyUI + rgthree-comfy + 烧入主模型
├── entrypoint.sh               # 启动 ComfyUI（输出指向 /tmp）+ handler
├── extra_model_paths.yaml      # 把 Network Volume 的 loras 接入 ComfyUI
├── handler.py                  # RunPod handler（ComfyUI websocket API）
├── workflow/
│   └── qwen_rapid_aio_api.json # Qwen-Rapid-AIO.json 的 API(prompt) 格式
├── setup_network_volume.sh     # 在挂卷 Pod 中下载全部 LoRA 到卷
├── requirements.txt
├── test_api.py                 # 本地调用 /runsync 测试
├── example_request.json        # 单图请求示例
├── example_request_2images.json
└── .env.example
```

## 部署步骤

### 1. 准备 Network Volume（放主模型 + LoRA）

1. 在 RunPod 创建一个 Network Volume（建议 ≥ 50GB，主模型约 28GB + LoRA）。
2. 起一个挂载了该卷的 Pod（默认挂载点 `/workspace`），在终端运行：
   ```bash
   VOLUME_DIR=/workspace bash setup_network_volume.sh
   ```
   脚本会用 `hf_transfer` 多线程下载主模型到卷的 `checkpoints/`，再下载 9 个 LoRA 到 `loras/`。Serverless 运行时该卷挂载在 `/runpod-volume`，内容一致。

### 2. 构建并推送镜像

镜像只含 ComfyUI + 节点，**不含模型**，构建很快（几分钟）：

```bash
docker build -t <your-registry>/qwen-rapid-aio:latest .
docker push <your-registry>/qwen-rapid-aio:latest
```

> 也可以直接用 RunPod Hub 从这个 GitHub 仓库自动构建（不再会超时）。

### 3. 创建 Serverless 端点

- 镜像填上一步推送的地址。
- 绑定第 1 步的 Network Volume（serverless 下自动挂载到 `/runpod-volume`）。
- GPU 建议 24GB 及以上（参考 `.runpod/hub.json`）。

## API

### 输入 `input`

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `prompt` | string | 是 | — | 编辑提示词 |
| `image_path` / `image_url` / `image_base64` | string | 是 | — | 第 1 张图（路径/URL/Base64 三选一） |
| `image_*_2` | string | 否 | — | 第 2 张图（同上三种形式，后缀 `_2`） |
| `image_*_3` | string | 否 | — | 第 3 张图（后缀 `_3`） |
| `seed` | int | 否 | 65454653 | 随机种子 |
| `steps` | int | 否 | 4 | 采样步数 |
| `cfg` | float | 否 | 1 | CFG |
| `sampler_name` | string | 否 | sa_solver | 采样器 |
| `scheduler` | string | 否 | beta | 调度器 |
| `denoise` | float | 否 | 1 | 去噪强度 |
| `width` / `height` | int | 否 | 768 | 输出尺寸 |
| `negative_prompt` | string | 否 | "" | 负向提示词 |
| `loras` | array | 否 | qwen_MCNL 开启 | LoRA 列表，见下 |
| `lora` + `lora_strength` | string+float | 否 | — | 便捷写法：单个 LoRA |

`loras` 数组元素：

```json
{ "on": true, "lora": "qwen_MCNL_v1.0.safetensors", "strength": 1.0, "strengthTwo": null }
```

可用 LoRA 文件名（需先放进 Network Volume）：

- `qwen_MCNL_v1.0.safetensors`（默认）
- `Qwen4Play-2512.1_e10.safetensors`
- `Meta4.safetensors`
- `bfs_v2_head_000007000.safetensors`
- `GiorgioV_Qwen4Play-2512.1_e10.safetensors`
- `qwen_image_edit_remove-clothing_v1.0.safetensors`
- `Qwen-Image-Edit-2511-Object-Remover-v2-9200.safetensors`
- `qe2511_consis_alpha_patched.safetensors`
- `Qwen4Play_v2.safetensors`

### 输出

成功：`{ "image": "<base64 png>" }`
失败：`{ "error": "..." }`

### 请求示例

```json
{
  "input": {
    "prompt": "add watercolor style, soft pastel tones",
    "image_url": "https://example.com/ref.jpg",
    "seed": 65454653,
    "width": 768,
    "height": 768,
    "loras": [
      { "on": true, "lora": "qwen_MCNL_v1.0.safetensors", "strength": 1.0 }
    ]
  }
}
```

## 本地测试

```bash
pip install requests
cp .env.example test.env   # 填入 RUNPOD_API_KEY 与 RUNPOD_ENDPOINT_ID

# URL 模式
python test_api.py --mode url --image-url "https://example.com/ref.jpg" --prompt "make it anime"

# base64 模式
python test_api.py --mode base64 --image-file ./input.png --prompt "remove background"

# 直接用 JSON 文件
python test_api.py --json example_request.json
```

## 致谢

- ComfyUI: https://github.com/comfyanonymous/ComfyUI
- rgthree-comfy（Power Lora Loader）: https://github.com/rgthree/rgthree-comfy
- 主模型 Qwen-Image-Edit-Rapid-AIO: https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO
