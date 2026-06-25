# =============================================================================
# Qwen-Image-Edit-2511 Rapid-AIO —— RunPod Serverless 镜像
#
# 架构：
#   主模型（AIO checkpoint，~28GB）  → Network Volume（/runpod-volume/checkpoints）
#   LoRA（几百 MB，经常换）          → Network Volume（/runpod-volume/loras）
#   推理临时输出                      → Container Disk 的 /tmp，用完即丢
#
# 说明：主模型不烧进镜像。RunPod Hub 构建有 30 分钟上限，烧入 28GB 模型会超时；
#       改为构建时只装 ComfyUI + 节点（几分钟完成），模型放卷里运行时加载。
#       若需"冷启动更快"的烧入方案，请在本地 docker build 后推送镜像（无时间限制）。
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
# 主模型不在此烧入镜像（见文件头说明）。
#   Qwen-Rapid-AIO-NSFW-v23.safetensors（AIO，含 MODEL/CLIP/VAE，~28GB）
#   请用 setup_network_volume.sh 预先下载到 Network Volume 的 checkpoints/ 目录，
#   运行时通过 extra_model_paths.yaml + entrypoint 软链接接入 ComfyUI。
# =============================================================================

# ---- 项目文件 ----
COPY . /workspace/
COPY extra_model_paths.yaml /ComfyUI/extra_model_paths.yaml

WORKDIR /workspace
RUN chmod +x /workspace/entrypoint.sh

CMD ["/workspace/entrypoint.sh"]
