#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 批量中英对照翻译（完整可用版 v2）
用法:
  python3 translate_batch.py <输入.md> <输出.md> [--verify]
  --verify: 只翻译前 10 段并打印对应关系（先验！必做）
缓存: /tmp/translation_cache.json（断点续跑）
特性: 3 并发 / 自动补翻循环（缺失段重试至多 5 轮）
"""
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

MODEL = 'deepseek-chat'      # ⚠️ 必须非 reasoning 模型
BATCH = 30
CONCURRENCY = 3
TEMPERATURE = 0.2
MAX_TOKENS = 8192
CACHE = '/tmp/translation_cache.json'
API_URL = 'https://api.deepseek.com/chat/completions'

# DeepSeek key（OpenClaw 配置）
def get_api_key():
    p = os.path.expanduser('~/.openclaw/agents/main/agent/models.json')
    if os.path.exists(p):
        d = json.load(open(p))
        k = d.get('providers', {}).get('deepseek', {}).get('apiKey')
        if k:
            return k
    return os.environ.get('DEEPSEEK_API_KEY', '')

API_KEY = ***

TERM_GLOSSARY = """术语表（可自定义）:
self-attention=自注意力; attention=注意力; token=*** embedding=嵌入表/嵌入;
logits=逻辑值; loss=损失; softmax=softmax; cross-entropy=交叉熵;
feedforward=前馈; layer norm=层归一化; residual connection=残差连接;
fine-tuning=微调; pretraining=预训练; bigram=二元模型;
Transformer=Transformer(保留); GPT=GPT(保留); batch=批次;
block size=块大小; context length=上下文长度; head=注意力头;
dropout=随机失活; optimizer=优化器; vocabulary=词表; encoder=编码器;
decoder=解码器; RLHF=RLHF(保留); reward model=奖励模型; nanoGPT=nanoGPT(保留)"""


def call_api(messages, max_tokens=MAX_TOKENS, retries=3):
    body = json.dumps({
        'model': MODEL, 'messages': messages,
        'max_tokens': max_tokens, 'temperature': TEMPERATURE,
    }).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=body, headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {API_KEY}'})
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())['choices'][0]['message']['content']
        except Exception as e:
            print(f'  [retry {attempt+1}] {e}', flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError('API failed')


def translate_batch(segments):
    """segments: [(global_idx, ci, si, ts, text)] -> {global_idx: cn}"""
    lines = [f'{gi}\t{ts}\t{text}' for gi, ci, si, ts, text in segments]
    prompt = f'''你是专业的中英技术翻译。以下是待翻译的英文转录片段（口语化），请把每条翻译成简体中文。

{TERM_GLOSSARY}

规则:
1. 只输出翻译结果, 每行格式: <序号>|<中文翻译>
2. 保留序号(必须与输入序号一致), 不要输出英文原文
3. 口语语气词(uh/um/okay/so)合理处理, 可省略或译为"呃/嗯/好的/那么"
4. 保持技术准确性, 术语按术语表; 翻译通顺自然

待翻译内容:
{chr(10).join(lines)}'''
    resp = call_api([
        {'role': 'system', 'content': '你是一位精通机器学习领域的中英翻译专家。'},
        {'role': 'user', 'content': prompt}])
    result = {}
    for line in resp.split('\n'):
        line = line.strip()
        if '|' in line:
            idx, cn = line.split('|', 1)
            try:
                result[int(idx.strip())] = cn.strip()
            except ValueError:
                pass
    return result


def parse_md(path):
    """解析 md: ## 章节 / **[ts]** 文本"""
    chapters = []
    cur = None
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if line.startswith('## '):
            cur = {'title': line[3:], 'segments': []}
            chapters.append(cur)
        elif line.startswith('**['):
            if cur is None:
                cur = {'title': '正文', 'segments': []}
                chapters.append(cur)
            end = line.index(']**')
            text = line[end + 3:].strip()
            if text:
                cur['segments'].append((line[3:end], text))
    return chapters


def main():
    if len(sys.argv) < 3:
        print('用法: python3 translate_batch.py <输入.md> <输出.md> [--verify]')
        sys.exit(1)
    SRC, DST = sys.argv[1], sys.argv[2]
    VERIFY = '--verify' in sys.argv

    chapters = parse_md(SRC)
    all_segs = []
    for ci, ch in enumerate(chapters):
        for si, (ts, text) in enumerate(ch['segments']):
            all_segs.append((len(all_segs), ci, si, ts, text))
    total = len(all_segs)
    print(f'章节: {len(chapters)}, 总段数: {total}')

    # 缓存加载（int key + chap_ 前缀章节）
    cache = {}
    if os.path.exists(CACHE):
        raw = json.load(open(CACHE, encoding='utf-8'))
        for k, v in raw.items():
            if str(k).startswith('chap_'):
                cache[k] = v
            else:
                cache[int(k)] = v
        print(f'缓存命中: {len(cache)} 条目')

    if VERIFY:
        print('== 先验模式：只翻译前 10 段 ==')
        batch = all_segs[:10]
        r = translate_batch(batch)
        for gi, ci, si, ts, text in batch:
            print(f'[{ts}] {text[:50]}')
            print(f'  -> {r.get(gi, "[缺失]")[:50]}')
        print('核对序号对应后，去掉 --verify 全量跑')
        return

    # 章节标题翻译
    chap_missing = [i for i, c in enumerate(chapters) if f'chap_{i}' not in cache]
    if chap_missing:
        print(f'>> 翻译 {len(chap_missing)} 个章节标题...')
        titles = [c['title'] for c in chapters]
        prompt = f'''把以下章节标题翻译成简体中文。\n格式: 每行 <序号>|<中文翻译>\n{TERM_GLOSSARY}\n\n标题列表:\n{chr(10).join(f"{i}|{c}" for i, c in enumerate(titles))}'''
        resp = call_api([{'role': 'system', 'content': '技术翻译专家'},
                         {'role': 'user', 'content': prompt}], max_tokens=4000)
        for line in resp.split('\n'):
            if '|' in line:
                idx, cn = line.split('|', 1)
                try:
                    cache[f'chap_{int(idx.strip())}'] = cn.strip()
                except ValueError:
                    pass
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'))

    # 分批并发翻译
    pending = [s for s in all_segs if s[0] not in cache]
    print(f'待翻译: {len(pending)} 段 (已完成 {total - len(pending)})')
    batches = [pending[i:i + BATCH] for i in range(0, len(pending), BATCH)]

    def work(batch):
        try:
            return translate_batch(batch)
        except Exception as e:
            print(f'  !! 批失败: {e}', flush=True)
            return {}

    done = 0
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for fut in [ex.submit(work, b) for b in batches]:
            cache.update(fut.result())
            done += 1
            if done % 10 == 0 or done == len(batches):
                json.dump(cache, open(CACHE, 'w', encoding='utf-8'))
                print(f'  进度: {done}/{len(batches)} 批, 缓存 {len(cache)} 条目', flush=True)
    json.dump(cache, open(CACHE, 'w', encoding='utf-8'))

    # 补翻循环：解析丢失的段自动重试，直到补完或轮数用尽
    for round_no in range(5):
        missing = [s for s in all_segs if s[0] not in cache]
        if not missing:
            break
        print(f'  补翻轮{round_no + 1}: 缺失 {len(missing)} 段', flush=True)
        for b in [missing[i:i + BATCH] for i in range(0, len(missing), BATCH)]:
            try:
                cache.update(translate_batch(b))
            except Exception as e:
                print(f'  !! 补翻失败: {e}', flush=True)
            time.sleep(0.3)
        json.dump(cache, open(CACHE, 'w', encoding='utf-8'))

    # 生成输出
    out = [f'# {os.path.basename(SRC)} — 中英对照\n', '> 翻译: DeepSeek API | 英文为原文\n']
    missing = 0
    for ci, ch in enumerate(chapters):
        out.append(f'\n## {ch["title"]}\n')
        if f'chap_{ci}' in cache:
            out.append(f'> {cache[f"chap_{ci}"]}\n')
        for si, (ts, text) in enumerate(ch['segments']):
            g = all_segs[[i for i, s in enumerate(all_segs) if s[1] == ci and s[2] == si][0]][0]
            cn = cache.get(g)
            if cn is None:
                cn = '[翻译缺失]'
                missing += 1
            out.append(f'**[{ts}]** {text}')
            out.append(f'> {cn}\n')
    with open(DST, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print(f'✅ 完成: {DST}')
    print(f'缺失: {missing}/{total}, 大小: {os.path.getsize(DST)} bytes')


if __name__ == '__main__':
    main()
