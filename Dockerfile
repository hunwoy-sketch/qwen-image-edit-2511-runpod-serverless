# =============================================================================
# Qwen-Image-Edit-2511 Rapid-AIO —— RunPod Serverless 镜像
#
# 架构：
#   主模型（AIO checkpoint，~14GB）  → 烧进镜像（Container Disk），冷启动快
#   LoRA（几百 MB，经常换）          → Network Volume（/runpod-volume/loras）
#   推理临时输出                      → Container Disk 的 /tmp，用完即丢
# =============================================================================
FROM wlsdml1114/multitalk-base:1.7 AS runtime

# URL 下载工具
RUN apt-get update && apt-get install -y wget git && rm -rf /var/lib/apt/lists/*

RUN pip install -U "huggingface_hub[hf_transfer]"
RUN pip install runpod websocket-client

WORKDIR /

# ---- ComfyUI 本体 ----
RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd ComfyUI && \
    pip install --no-cache-dir -r requirements.txt

# ---- 自定义节点：ComfyUI-Manager ----
RUN cd /ComfyUI/custom_nodes/ && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    cd ComfyUI-Manager && \
    pip install --no-cache-dir -r requirements.txt

# ---- 自定义节点：rgthree-comfy（提供 Power Lora Loader）----
RUN cd /ComfyUI/custom_nodes/ && \
    git clone https://github.com/rgthree/rgthree-comfy.git && \
    cd rgthree-comfy && \
    (pip install --no-cache-dir -r requirements.txt || true)

# ---- 模型目录 ----
RUN mkdir -p /ComfyUI/models/checkpoints /ComfyUI/models/loras /ComfyUI/input

# =============================================================================
# 主模型：烧进镜像（Container Disk）
#   Qwen-Rapid-AIO-NSFW-v23.safetensors —— AIO checkpoint，含 MODEL/CLIP/VAE
#   来源：https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO
# =============================================================================
ENV HF_HUB_ENABLE_HF_TRANSFER=1
RUN wget -q --show-progress \
    https://huggingface.co/Phr00t/Qwen-Image-Edit-Rapid-AIO/resolve/main/v23/Qwen-Rapid-AIO-NSFW-v23.safetensors \
    -O /ComfyUI/models/checkpoints/Qwen-Rapid-AIO-NSFW-v23.safetensors

# ---- 项目文件 ----
COPY . /workspace/
COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml

WORKDIR /workspace
RUN chmod +x /workspace/entrypoint.sh

CMD ["/workspace/entrypoint.sh"]
