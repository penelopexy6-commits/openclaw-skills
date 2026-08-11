#!/usr/bin/env python3
"""
vision_look.py — 图片识别工具（硅基流动 Qwen3-VL）

用途：给 AI 提供「看图」能力（DS 是纯文本模型，看不了图）
流程：图片路径/URL → 调硅基流动 Qwen3-VL → 返回结构化识别结果

用法：
  python3 vision_look.py --image /path/to/img.png
  python3 vision_look.py --image https://example.com/img.jpg --prompt "识别图中的文字"
  python3 vision_look.py --image img.png --model Qwen/Qwen3-VL-32B-Instruct
"""
import argparse
import base64
import json
import os
import sys
import urllib.request
import urllib.error

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
API_URL = "https://api.siliconflow.cn/v1/chat/completions"

SCENE_PROMPTS = {
    "describe": "请用中文详细描述这张图片的内容：主体、场景、文字、细节。",
    "ocr": "请完整提取图片中的所有文字内容，按出现顺序列出。",
    "ecommerce": "这是一张电商商品图。请分析：1) 商品是什么 2) 图片上的所有文字 3) 卖点展示 4) 构图和设计风格 5) 可以优化的地方",
    "review": "这是一张电商评价/截图。请提取：1) 图中所有文字 2) 评价是好评还是差评 3) 用户提到的核心问题",
}


def load_key():
    secrets_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.secrets")
    secrets_path = os.path.abspath(secrets_path)
    for line in open(secrets_path, encoding="utf-8"):
        line = line.strip()
        if line.startswith("SILICONFLOW_API_KEY"):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key:
                return key
    if os.environ.get("SILICONFLOW_API_KEY"):
        return os.environ["SILICONFLOW_API_KEY"]
    raise SystemExit("❌ 未找到 SILICONFLOW_API_KEY（.env.secrets 或环境变量）")


def image_to_data_url(image_path):
    if not os.path.exists(image_path):
        raise SystemExit(f"❌ 图片不存在: {image_path}")
    ext = os.path.splitext(image_path)[1].lower()
    mime = {"": "image/png", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
            ".bmp": "image/bmp"}.get(ext, "image/png")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def call_vision(image_url, prompt, model):
    key = load_key()
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 1024,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        r = urllib.request.urlopen(req, timeout=120)
        d = json.loads(r.read())
        content = d["choices"][0]["message"]["content"]
        usage = d.get("usage", {})
        return content, usage
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:500]
        raise SystemExit(f"❌ API 错误 {e.code}: {err}")


def main():
    ap = argparse.ArgumentParser(description="图片识别（硅基流动 Qwen3-VL）")
    ap.add_argument("--image", required=True, help="本地图片路径或 http(s) URL")
    ap.add_argument("--prompt", help="自定义问题（默认描述图片）")
    ap.add_argument("--scene", choices=list(SCENE_PROMPTS.keys()),
                    help="场景模板：describe/ocr/ecommerce/review")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"模型（默认 {DEFAULT_MODEL}）")
    args = ap.parse_args()

    if args.scene:
        prompt = SCENE_PROMPTS[args.scene]
    elif args.prompt:
        prompt = args.prompt
    else:
        prompt = SCENE_PROMPTS["describe"]

    if args.image.startswith(("http://", "https://")):
        img_url = args.image
    else:
        img_url = image_to_data_url(args.image)

    print(f"🔍 识别中 [{args.model}] ...", file=sys.stderr)
    content, usage = call_vision(img_url, prompt, args.model)
    print(content)
    print(f"\n---\n[tokens: {usage.get('total_tokens', '?')}]", file=sys.stderr)


if __name__ == "__main__":
    main()
