#!/usr/bin/env python3
"""
Qwen-Image-Edit-2511 Rapid-AIO RunPod API 测试脚本
按 handler 输入规范调用 /runsync，并保存返回的图片。

环境变量（可写在同目录的 test.env，或直接 export）：
  RUNPOD_API_KEY        RunPod API Key（必填）
  RUNPOD_ENDPOINT_ID    Serverless 端点 ID（必填）
  TEST_IMAGE_URL        URL 模式下的测试图片地址（可选）
"""

import os
import sys
import json
import base64
import argparse
from pathlib import Path


def _load_test_env():
    env_path = Path(__file__).resolve().parent / "test.env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    os.environ.setdefault(k, v)


_load_test_env()

try:
    import requests
except ImportError:
    print("需要 requests: pip install requests")
    sys.exit(1)


def get_config():
    api_key = os.getenv("RUNPOD_API_KEY") or os.getenv("runpod_API_KEY")
    endpoint_id = os.getenv("RUNPOD_ENDPOINT_ID") or os.getenv("qwen_rapid_aio")
    if not api_key or not endpoint_id:
        print("必填环境变量：RUNPOD_API_KEY、RUNPOD_ENDPOINT_ID")
        return None, None
    return api_key.strip(), endpoint_id.strip()


def run_sync(api_key, endpoint_id, input_payload, timeout=300):
    wait_ms = min(300000, max(60000, timeout * 1000))
    url = f"https://api.runpod.ai/v2/{endpoint_id}/runsync?wait={wait_ms}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r = requests.post(url, json={"input": input_payload}, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def encode_file(path):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return base64.b64encode(p.read_bytes()).decode("utf-8")


def main():
    parser = argparse.ArgumentParser(description="Qwen Rapid-AIO API 测试")
    parser.add_argument("--json", "-j", help="输入 JSON 文件（含 input 对象或整体 {\"input\":{...}}）")
    parser.add_argument("--mode", choices=["url", "base64"], default="url", help="输入方式")
    parser.add_argument("--image-url", help="测试图片 URL")
    parser.add_argument("--image-file", help="本地图片文件（base64 模式）")
    parser.add_argument("--prompt", default="add watercolor style, soft pastel tones", help="编辑提示词")
    parser.add_argument("--lora", help="指定单个 LoRA 文件名（可选）")
    parser.add_argument("--lora-strength", type=float, default=1.0, help="LoRA 权重")
    parser.add_argument("--seed", type=int, default=65454653)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--out", "-o", default="out_test.png", help="保存路径")
    args = parser.parse_args()

    api_key, endpoint_id = get_config()
    if not api_key or not endpoint_id:
        sys.exit(1)

    if args.json:
        with open(args.json, encoding="utf-8") as f:
            data = json.load(f)
        input_payload = data.get("input", data)
    else:
        input_payload = {
            "prompt": args.prompt,
            "seed": args.seed,
            "steps": args.steps,
            "width": args.width,
            "height": args.height,
        }
        if args.mode == "url":
            url = args.image_url or os.getenv("TEST_IMAGE_URL")
            if not url:
                print("需要 --image-url 或 TEST_IMAGE_URL")
                sys.exit(1)
            input_payload["image_url"] = url
        else:
            if not args.image_file:
                print("base64 模式需要 --image-file")
                sys.exit(1)
            input_payload["image_base64"] = encode_file(args.image_file)
        if args.lora:
            input_payload["lora"] = args.lora
            input_payload["lora_strength"] = args.lora_strength

    # 打印（截断 base64）
    printable = dict(input_payload)
    for k in ["image_base64", "image_base64_2", "image_base64_3"]:
        if k in printable and isinstance(printable[k], str):
            printable[k] = f"<base64:{len(printable[k])} chars>"
    print("Input:", json.dumps(printable, indent=2, ensure_ascii=False))
    print("\n调用 RunPod /runsync ...")

    try:
        result = run_sync(api_key, endpoint_id, input_payload, timeout=args.timeout)
    except requests.exceptions.RequestException as e:
        print("请求失败:", e)
        if hasattr(e, "response") and e.response is not None:
            print("响应:", e.response.text[:800])
        sys.exit(1)

    status = result.get("status")
    output = result.get("output")
    print("\nStatus:", status)

    if isinstance(output, dict) and "error" in output:
        print("Error:", output["error"])
        sys.exit(1)
    if isinstance(output, dict) and "image" in output:
        raw = base64.b64decode(output["image"])
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(raw)
        print("已保存:", args.out)
        sys.exit(0)

    print("完整响应:", json.dumps(result, indent=2, ensure_ascii=False)[:1500])
    sys.exit(0 if status == "COMPLETED" else 1)


if __name__ == "__main__":
    main()
