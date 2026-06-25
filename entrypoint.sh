#!/bin/bash
# =============================================================================
# RunPod Serverless 启动脚本
#   1. 校验 CUDA
#   2. 接入 Network Volume 上的 LoRA（/runpod-volume/loras）
#   3. 临时输出指向 /tmp（用完即丢，无需持久化）
#   4. 后台启动 ComfyUI，前台运行 handler
# =============================================================================
set -e

echo "===== 检查 CUDA ====="
python3 -c "
import torch, sys
try:
    if torch.cuda.is_available():
        print('CUDA 可用:', torch.cuda.get_device_name(0)); sys.exit(0)
    print('CUDA 不可用'); sys.exit(1)
except Exception as e:
    print('CUDA 检查异常:', e); sys.exit(2)
"
if [ $? -ne 0 ]; then
    echo "错误：CUDA 不可用，退出。"
    exit 1
fi
export CUDA_VISIBLE_DEVICES=0
export FORCE_CUDA=1

# -----------------------------------------------------------------------------
# 接入 Network Volume 的主模型（checkpoints）
#   serverless：卷挂载在 /runpod-volume
#   extra_model_paths.yaml 已把 /runpod-volume/checkpoints 接入 ComfyUI，
#   这里再做一次软链兜底，并校验主模型是否存在。
# -----------------------------------------------------------------------------
VOLUME_CKPTS="/runpod-volume/checkpoints"
if [ -d "$VOLUME_CKPTS" ]; then
    echo "===== 检测到 Network Volume checkpoints 目录: $VOLUME_CKPTS ====="
    ls -1 "$VOLUME_CKPTS" 2>/dev/null | head -n 20 || true
    mkdir -p /ComfyUI/models/checkpoints
    for f in "$VOLUME_CKPTS"/*; do
        [ -e "$f" ] || continue
        name=$(basename "$f")
        target="/ComfyUI/models/checkpoints/$name"
        if [ ! -e "$target" ]; then
            ln -s "$f" "$target"
        fi
    done
else
    echo "警告：未发现 $VOLUME_CKPTS。请先运行 setup_network_volume.sh 下载主模型到卷。"
fi

# -----------------------------------------------------------------------------
# 接入 Network Volume 的 LoRA
#   serverless：卷挂载在 /runpod-volume
#   优先用 extra_model_paths.yaml（Dockerfile 已拷入），这里再做一次软链兜底，
#   保证 /ComfyUI/models/loras 也能看到卷内 LoRA。
# -----------------------------------------------------------------------------
VOLUME_LORAS="/runpod-volume/loras"
if [ -d "$VOLUME_LORAS" ]; then
    echo "===== 检测到 Network Volume LoRA 目录: $VOLUME_LORAS ====="
    ls -1 "$VOLUME_LORAS" 2>/dev/null | head -n 20 || true
    # 将卷内 LoRA 软链到 ComfyUI loras 目录（不覆盖镜像内已有文件）
    mkdir -p /ComfyUI/models/loras
    for f in "$VOLUME_LORAS"/*; do
        [ -e "$f" ] || continue
        name=$(basename "$f")
        target="/ComfyUI/models/loras/$name"
        if [ ! -e "$target" ]; then
            ln -s "$f" "$target"
        fi
    done
else
    echo "提示：未发现 $VOLUME_LORAS。请确认已挂载 Network Volume 并放入 LoRA。"
    echo "      （可先运行 setup_network_volume.sh 在挂卷的 Pod 中下载 LoRA）"
fi

# -----------------------------------------------------------------------------
# 临时输出目录指向 /tmp（Container Disk，用完即丢）
# -----------------------------------------------------------------------------
mkdir -p /tmp/comfy_output /tmp/comfy_temp
COMFY_OUTPUT_ARGS="--output-directory /tmp/comfy_output --temp-directory /tmp/comfy_temp"

# -----------------------------------------------------------------------------
# 启动 ComfyUI
# -----------------------------------------------------------------------------
echo "===== 后台启动 ComfyUI ====="
python /ComfyUI/main.py --listen --use-sage-attention $COMFY_OUTPUT_ARGS &

echo "===== 等待 ComfyUI 就绪 ====="
max_wait=120
wait_count=0
while [ $wait_count -lt $max_wait ]; do
    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "ComfyUI 已就绪！"
        break
    fi
    echo "等待 ComfyUI... ($wait_count/$max_wait)"
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "错误：ComfyUI 在 ${max_wait}s 内未能启动。"
    exit 1
fi

echo "===== 启动 handler ====="
exec python /workspace/handler.py
