#!/bin/bash
# =============================================================================
# Network Volume 初始化脚本
#
# 用途：在“挂载了 Network Volume 的 RunPod Pod”中运行一次，
#       把全部 LoRA 下载到卷的 loras/ 目录。Serverless 运行时即可共享。
#
# 用法：
#   1. 在 RunPod 创建一个 Pod，挂载目标 Network Volume（默认挂载点 /workspace）
#   2. 在 Pod 终端执行：
#        VOLUME_DIR=/workspace bash setup_network_volume.sh
#      （serverless 运行时该卷会挂载在 /runpod-volume，目录内容相同）
#
# 架构说明：
#   主模型（AIO checkpoint）已烧进镜像，无需放卷。
#   本脚本只负责经常更换的 LoRA。
# =============================================================================
set -e

# 卷在 Pod 中的挂载点（serverless 时为 /runpod-volume，二者内容一致）
VOLUME_DIR="${VOLUME_DIR:-/workspace}"
LORAS_DIR="$VOLUME_DIR/loras"

HF_BASE="https://huggingface.co"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERR]${NC}   $1"; }

download() {
    local url="$1"; local dest="$2"
    local name; name=$(basename "$dest")
    if [[ -f "$dest" ]]; then
        warn "已存在，跳过：$name"
        return 0
    fi
    info "下载：$name"
    if wget -q --show-progress -c -O "$dest" "$url"; then
        info "完成：$name"
    else
        error "失败：$name  URL: $url"
        rm -f "$dest"
        return 1
    fi
}

mkdir -p "$LORAS_DIR"
info "LoRA 下载目录：$LORAS_DIR"
echo ""

# -- QWEN_MCNL / anime [工作流默认激活] --
download \
    "$HF_BASE/laoK888/Qwen-lora/resolve/main/QWEN_MCNL/qwen_MCNL_v1.0.safetensors" \
    "$LORAS_DIR/qwen_MCNL_v1.0.safetensors"

# -- Qwen4Play --
download \
    "$HF_BASE/laoK888/Qwen-lora/resolve/main/Qwen4Play/Qwen4Play-2512.1_e10.safetensors" \
    "$LORAS_DIR/Qwen4Play-2512.1_e10.safetensors"

# -- Multiple-Angles / Meta4 --
download \
    "$HF_BASE/wiikoo/Qwen-lora-nsfw/resolve/main/loras/Meta4.safetensors" \
    "$LORAS_DIR/Meta4.safetensors"

# -- Real PS / light-restoration --
download \
    "$HF_BASE/wiikoo/Qwen-lora-nsfw/resolve/main/loras/bfs_v2_head_000007000.safetensors" \
    "$LORAS_DIR/bfs_v2_head_000007000.safetensors"

# -- relight (GiorgioV) [重命名前缀避免与 laoK888 同名冲突] --
download \
    "$HF_BASE/GiorgioV/Qwen_test/resolve/main/Qwen4Play-2512.1_e10.safetensors" \
    "$LORAS_DIR/GiorgioV_Qwen4Play-2512.1_e10.safetensors"

# -- Jib / multi-angle-lighting --
download \
    "$HF_BASE/wiikoo/Qwen-lora-nsfw/resolve/main/loras/qwen_image_edit_remove-clothing_v1.0.safetensors" \
    "$LORAS_DIR/qwen_image_edit_remove-clothing_v1.0.safetensors"

# -- A2R_2509_Base / edit-skin --
download \
    "$HF_BASE/prithivMLmods/QIE-2511-Object-Remover-v2/resolve/main/Qwen-Image-Edit-2511-Object-Remover-v2-9200.safetensors" \
    "$LORAS_DIR/Qwen-Image-Edit-2511-Object-Remover-v2-9200.safetensors"

# -- Next-Scene --
download \
    "$HF_BASE/GiorgioV/Qwen_test/resolve/main/qe2511_consis_alpha_patched.safetensors" \
    "$LORAS_DIR/qe2511_consis_alpha_patched.safetensors"

# -- V14-10 / upscale-image --
download \
    "$HF_BASE/wiikoo/Qwen-lora-nsfw/resolve/main/loras/Qwen4Play_v2.safetensors" \
    "$LORAS_DIR/Qwen4Play_v2.safetensors"

echo ""
info "===== 全部 LoRA 下载完成 ====="
info "卷内 LoRA 目录：$LORAS_DIR"
warn "Serverless 运行时该卷挂载在 /runpod-volume，LoRA 路径为 /runpod-volume/loras"
