---
name: "vision-look"
description: "图片识别/视觉理解：AI 看图能力（硅基流动 Qwen3-VL），支持 OCR、电商图分析、评价截图解读"
---

# vision-look — 看图（图片识别）

给 AI 提供视觉能力：主模型是纯文本模型（DeepSeek V4 Flash），看不了图片。
本 Skill 用硅基流动 Qwen3-VL（免费级）做「眼睛」，主模型做「大脑」。

## 何时使用

- 用户发来/提到一张图片，需要知道图里是什么
- 需要提取图片中的文字（OCR）
- 电商场景：竞品主图分析、自家商品图审核、评价/差评截图解读
- 截图分析：后台页面、报表截图、聊天记录截图

## 如何使用

```bash
# 基础：描述图片
python3 ~/.openclaw/workspace/scripts/vision_look.py --image <路径或URL>

# OCR：提取图中文字
python3 ~/.openclaw/workspace/scripts/vision_look.py --image <图> --scene ocr

# 电商图分析（商品/文字/卖点/构图/优化建议）
python3 ~/.openclaw/workspace/scripts/vision_look.py --image <图> --scene ecommerce

# 评价截图解读（好评/差评/核心问题）
python3 ~/.openclaw/workspace/scripts/vision_look.py --image <图> --scene review

# 自定义问题
python3 ~/.openclaw/workspace/scripts/vision_look.py --image <图> --prompt "图里有几个产品？颜色分别是什么？"

# 换更强模型（付费级，识别更准）
python3 ~/.openclaw/workspace/scripts/vision_look.py --image <图> --model Qwen/Qwen3-VL-30B-A3B-Instruct
```

## 场景模板（--scene）

| scene | 用途 |
|---|---|
| describe（默认） | 详细描述图片内容 |
| ocr | 完整提取图中文字 |
| ecommerce | 电商商品图：商品/文字/卖点/构图/优化建议 |
| review | 评价截图：文字/好评差评/核心问题 |

## 可用模型（--model）

| 模型 | 成本 | 说明 |
|---|---|---|
| `Qwen/Qwen3-VL-8B-Instruct` | 免费级 | 默认，日常够用 |
| `Qwen/Qwen3-VL-30B-A3B-Instruct` | 低价 | MoE，能力接近 32B |
| `Qwen/Qwen3-VL-32B-Instruct` | 付费 | 高精度复杂图 |
| `Qwen/Qwen3-VL-32B-Thinking` | 付费 | 带推理 |
| `Qwen/Qwen3-Omni-30B-A3B-Instruct` | 付费 | 全模态（图+音+视频） |

## 依赖与配置

- 脚本：`scripts/vision_look.py`（workspace 下）
- API key：`workspace/.env.secrets` 里 `SILICONFLOW_API_KEY`（已配置）
- 支持：本地图片路径 / http(s) URL
- 本地无 GPU 也能用（模型跑在硅基流动云端）

## 踩坑记录

- 大图（>2MB）会增大 token 消耗（base64 传输），必要时先压缩
- 8B 模型对小字 OCR 偶尔漏字，重要文字识别用 32B 复核
- 一次只能看一张图（多图需逐张调用后汇总）
