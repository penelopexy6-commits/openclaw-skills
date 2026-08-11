---
name: "deepseek-batch-translation"
description: "DeepSeek API 批量中英对照翻译：md 解析、分批调用、缓存续跑、补翻循环、并发加速、对照格式输出"
---

# deepseek-batch-translation — DeepSeek 批量中英对照翻译

## 用途
把长文档（视频转录、文章、md 笔记）批量翻译成中英对照格式，输出到 Obsidian/Markdown。
实测 1106 段转录：deepseek-chat + 3 并发 ≈ 5-7 分钟，成本约 ¥0.1。

## 适用场景
- YouTube 视频转录 → 中英对照学习笔记
- 英文技术文档 → 中英对照
- 任何按"段落"组织的长文本

## 前置条件
- DeepSeek API key（`OpenClaw 模型配置文件 models.json（agents/main/agent/ 下）` → `providers.deepseek.apiKey`）
- Python 3（urllib 即可，无需第三方依赖）

## 核心流程
1. **解析输入 md**：`## 标题` 为章节，`**[HH:MM:SS]** 文本` 或 `**序号**` 为段落
2. **先验 1 批（必做）**：只翻译 10 段，人工核对序号对应关系，再全量跑
3. **分批调用**：30 段/批，3 线程并发，模型用 `deepseek-chat`
4. **缓存续跑**：每批结果实时写入 `/tmp/translation_cache.json`，中断后重跑自动跳过已完成
5. **补翻循环**：解析丢失的段（模型输出格式不符）自动重试，最多 5 轮直到补完
6. **生成对照**：英文原文 + `> 中文翻译`（Obsidian 引用块），章节标题双语
7. **完成验证（必做）**：`grep -c "翻译缺失" 输出.md` 必须为 0；确认无残留翻译进程

## 用法
```bash
# 先验（必做，10 段核对对应关系）
python3 scripts/translate_batch.py 输入.md 输出.md --verify

# 全量（自动补翻，跑完缺失应为 0）
python3 scripts/translate_batch.py 输入.md 输出.md

# 验证
grep -c "翻译缺失" 输出.md   # 必须为 0
```

## 关键参数
```python
MODEL = 'deepseek-chat'          # ⚠️ 必须非 reasoning 模型
BATCH = 30                        # 段/批
CONCURRENCY = 3                   # 并发线程
TEMPERATURE = 0.2                 # 翻译要稳定
MAX_TOKENS = 8192
```

## ⚠️ 踩坑防护（必读）
1. **禁用 reasoning 模型**（deepseek-v4-flash/pro）：reasoning 模型大批次思考过程吃光 max_tokens → content 返回空 → 整批缺失。必须用 `deepseek-chat`
2. **全局序号**：批内序号(0-29) 与全局序号(0-1105) 必须分开管理，用全局索引做缓存 key，否则翻译错位（v1 血泪）
3. **先小样本验证再全量**：10 段测试输出格式，核对序号对应，别直接全量跑
4. **缓存 key 类型**：json 序列化后 int key 变 str，加载时 `int(k)` 转换；章节标题用 `chap_<i>` 前缀区分
5. **写文件用全局索引查缓存**：不要用元组/复杂表达式当 key
6. **只跑一个翻译进程，杀进程杀整棵树**：多个翻译进程并存时，`kill <bash父进程>` 只杀 bash，python 子进程成孤儿继续跑，几十分钟后写完"全缺失"垃圾结果**覆盖正确产物**。杀进程用 `pkill -f translate_batch`，杀完 `ps aux | grep` 验证无残留
7. **产物完成后立即验证 + 缓存别急着删**：`grep -c "翻译缺失"` 确认 0 再清理 `/tmp/translation_cache.json`；重要产物尽早 git commit 备份

> 完整踩坑案例（背景/现象/原因/解法）见 `references/踩坑记录.md`

## 脚本
见 `scripts/translate_batch.py`（完整可用版，含 --verify 先验模式 + 自动补翻循环）

## 输出格式示例
```markdown
## THE CRUX OF THE VIDEO: version 4: self-attention
> 视频核心：版本4：自注意力

**[01:02:05]** okay so now we get the Crux of self attention
> 好了，现在我们来到自注意力的核心
```
