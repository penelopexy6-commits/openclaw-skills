#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cluster_pipeline_v2.py — 画像管线第二版验证：先聚类，后打标
=====================================================================
链路: review_analysis(第一版 LLM 标签=ground truth)
      → bge-m3 向量化 → HDBSCAN 聚类
      → 每簇抽 3 条代表喂 LLM 打标 → 标签继承给全簇成员
      → 与第一版逐条标签对比一致率（≥80% 达标）

用法:
  .venv/bin/python scripts/cluster_pipeline_v2.py [--category 泳衣] [--min-cluster-size 5] [--threshold 0.85]

输出:
  /tmp/cluster_report_<category>.json   一致率对比 + 簇明细
  /tmp/cluster_report_<category>.md     人类可读报告
=====================================================================
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import numpy as np
import psycopg2
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_config import DB

# ---------- embedding（硅基流动 bge-m3，免费） ----------
EMB_URL = "https://api.siliconflow.cn/v1/embeddings"
EMB_MODEL = "BAAI/bge-m3"
# Key 从环境变量读（禁止硬编码）；本地开发见 workspace/.env.secrets
import os as _os
if _os.path.exists(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".env.secrets")):
    for _line in open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", ".env.secrets"), encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            _os.environ.setdefault(_k.strip(), _v.strip())
EMB_KEY = _os.environ.get("SILICONFLOW_API_KEY", "")
EMB_BATCH = 32
EMB_CONCURRENCY = 8

# ---------- LLM 打标（DeepSeek） ----------
MODEL = "deepseek-chat"
API_URL = "https://api.deepseek.com/chat/completions"
KEY_FILE = "{MODELS_JSON}"
REPRESENTATIVES = 3   # 每簇抽几条代表

SHORT_TEXT_WORDS = 1  # 少于 N 个词的短评论不参与聚类（1=全部参与，短文本靠质心匹配继承）

PAIN_CN = {"size": "尺码偏小/不符", "quality": "质量差", "wrong_item": "发错货/二手", "fading": "褪色掉色",
           "chest_support": "胸部支撑不足", "workmanship": "做工瑕疵", "missing_parts": "缺件漏发",
           "fit_shape": "版型/上身效果", "fabric": "面料问题", "pilling": "勾丝起球",
           "none": "无明显痛点", "other": "其他"}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_deepseek_key():
    with open(KEY_FILE) as f:
        return json.load(f)["providers"]["deepseek"]["apiKey"]


def db_conn():
    return psycopg2.connect(**DB)


# =====================================================================
# Step 1: 取数据（第一版 LLM 标签 = ground truth）
# =====================================================================
def load_ground_truth(category: str):
    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute("""SELECT review_id, score, text, pain_point, emotion, body_feature,
                              usage_scene, purchase_reason
                       FROM review_analysis WHERE category=%s ORDER BY review_id""", (category,))
        rows = cur.fetchall()
    conn.close()
    items = []
    for rid, score, text, pain, emo, body, scene, reason in rows:
        text = (text or "").strip()
        items.append({
            "review_id": rid, "score": score, "text": text,
            "pain_point": pain, "emotion": emo, "body_feature": body,
            "usage_scene": scene, "purchase_reason": reason,
            "n_words": len(text.split()),
        })
    return items


# =====================================================================
# Step 2: bge-m3 向量化
# =====================================================================
def embed(texts):
    for attempt in range(3):
        try:
            r = requests.post(EMB_URL, headers={"Authorization": f"Bearer {EMB_KEY}"},
                              json={"model": EMB_MODEL, "input": texts}, timeout=90)
            r.raise_for_status()
            data = r.json()["data"]
            return [d["embedding"] for d in sorted(data, key=lambda x: x["index"])]
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def vectorize(items):
    texts = [it["text"] for it in items]
    vecs = [None] * len(texts)
    with ThreadPoolExecutor(max_workers=EMB_CONCURRENCY) as pool:
        futs = {}
        for bi, batch in enumerate(chunks(list(enumerate(texts)), EMB_BATCH)):
            futs[pool.submit(embed, [t for _, t in batch])] = (bi, batch)
        for fut in as_completed(futs):
            bi, batch = futs[fut]
            out = fut.result()
            for (idx, _), vec in zip(batch, out):
                vecs[idx] = vec
    return np.array(vecs, dtype=np.float32)


# =====================================================================
# Step 3: HDBSCAN 聚类
# =====================================================================
def cluster(vecs, min_cluster_size):
    import hdbscan
    # bge-m3 向量建议 L2 归一化后用欧氏距离（等价余弦）
    norm = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    cl = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=1,
                         metric="euclidean", cluster_selection_method="eom")
    labels = cl.fit_predict(norm)
    return labels, cl


# =====================================================================
# Step 4: 每簇抽代表 → LLM 打标
# =====================================================================
PROMPT_TMPL = """你是俄罗斯电商消费者画像分析师。分析以下俄语泳衣评论，逐条提取结构化信息。

严格输出 JSON 数组，每条格式：
{{"id": 序号, "pain_point": "枚举值", "emotion": "枚举值", "body_feature": "枚举值", "usage_scene": "枚举值", "purchase_reason": "枚举值"}}

枚举说明：
- pain_point: size=尺码问题, chest_support=胸部支撑, missing_parts=缺件漏发, wrong_item=发错货/二手, quality=质量差, pilling=勾丝起球, fading=褪色, workmanship=做工瑕疵, fit_shape=版型/上身效果, fabric=面料, none=无明显痛点, other=其他
- emotion: positive=满意, neutral=一般, negative=失望, angry=愤怒
- body_feature: slim=苗条, normal=普通, plus_size=丰满/大码, big_bust=大胸, unknown=无法判断
- usage_scene: pool=泳池, vacation=度假/海滩, sport=运动游泳, sauna=桑拿, gift=送礼, daily=日常, unknown=无法判断
- purchase_reason: slimming=显瘦塑形, comfort=舒适, design=设计好看, quality=质量好, price=价格, support=支撑好, brand=品牌, unknown=无

只输出 JSON，不要任何解释。无法判断的字段用 unknown。

评论列表（每条以 [序号] 开头，输出时 id 必须严格等于该序号，例如第一条 id=1）：
{items}"""


def call_api(messages, retries=3):
    body = json.dumps({
        "model": MODEL, "messages": messages, "temperature": 0.1, "max_tokens": 3000,
    }).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=body, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {get_deepseek_key()}"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def parse_json_array(out):
    m = re.search(r"\[\s*\{.*\}\s*\]", out, re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except Exception:
        return []


def llm_label(segments):
    """segments: [(review_id, text), ...] → {review_id: labels}"""
    lines = "\n".join(f"[{i+1}] {t}" for i, (_, t) in enumerate(segments))
    prompt = PROMPT_TMPL.format(items=lines)
    out = call_api([
        {"role": "system", "content": "你是俄罗斯电商消费者画像分析师，只输出严格 JSON。"},
        {"role": "user", "content": prompt},
    ])
    result = {}
    for pos, item in enumerate(parse_json_array(out)):
        idx = item.get("id")
        rid = None
        if isinstance(idx, int) and 1 <= idx <= len(segments):
            rid = segments[idx - 1][0]
        elif 0 <= pos < len(segments):
            rid = segments[pos][0]
        if rid is not None:
            result[str(rid)] = {
                "pain_point": item.get("pain_point", "other"),
                "emotion": item.get("emotion", "neutral"),
                "body_feature": item.get("body_feature", "unknown"),
                "usage_scene": item.get("usage_scene", "unknown"),
                "purchase_reason": item.get("purchase_reason", "unknown"),
            }
    return result


def label_clusters(items, labels, min_cluster_size, threshold=0.85):
    """给每个簇打标：抽代表 LLM 打标 → 投票得簇标签 → 继承给全簇

    噪声点/未聚类点：先和簇质心做余弦匹配，>threshold 直接继承（0 成本），
    匹配不上的才走 LLM 兜底。
    """
    n_clusters = max(labels) + 1
    members = {}
    for it, lab in zip(items, labels):
        members.setdefault(lab, []).append(it)

    cluster_labels = {}   # lab -> {field: value}
    llm_calls = 0
    llm_labeled = 0

    # 代表集合：每簇取离质心最近的 REPRESENTATIVES 条
    centroids = {}   # lab -> 归一化质心向量
    for lab, mem in members.items():
        if lab == -1:
            cluster_labels[lab] = None
            continue
        vecs = np.array([it["_vec"] for it in mem], dtype=np.float32)
        centroid = vecs.mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        centroids[lab] = centroid
        dists = np.linalg.norm(vecs - centroid, axis=1)
        k = min(REPRESENTATIVES, len(mem))
        rep_idx = np.argsort(dists)[:k]
        reps = [mem[i] for i in rep_idx]
        segs = [(r["review_id"], r["text"][:400]) for r in reps]
        labels_map = llm_label(segs)
        llm_calls += 1
        llm_labeled += len(labels_map)
        # 投票：每个字段取众数
        vote = {}
        for field in ("pain_point", "emotion", "body_feature", "usage_scene", "purchase_reason"):
            vals = [labels_map.get(str(r["review_id"]), {}).get(field) for r in reps]
            vals = [v for v in vals if v and v != "unknown"]
            if not vals:
                vals = [labels_map.get(str(r["review_id"]), {}).get(field) for r in reps]
            vals = [v for v in vals if v]
            vote[field] = max(set(vals), key=vals.count) if vals else "unknown"
        cluster_labels[lab] = vote

    # 继承：全簇成员打簇标签
    inherited = {}
    for lab, mem in members.items():
        if lab == -1 or cluster_labels.get(lab) is None:
            continue
        for it in mem:
            inherited[it["review_id"]] = dict(cluster_labels[lab])

    # 质心矩阵（归一化）
    lab_list = sorted(centroids.keys())
    C = np.array([centroids[l] for l in lab_list])  # (n_clusters, dim)

    def match_inherit(pool, label):
        """pool: [item,...] 未聚类点；返回 (继承数, 待LLM列表)"""
        if not pool or len(lab_list) == 0:
            return 0, pool
        vecs = np.array([it["_vec"] for it in pool], dtype=np.float32)
        vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        sim = vecs @ C.T  # (n, n_clusters)
        best = sim.max(axis=1)
        inherited_n = 0
        pending = []
        for it, s, bi in zip(pool, best, sim.argmax(axis=1)):
            if s >= threshold:
                inherited[it["review_id"]] = dict(cluster_labels[lab_list[bi]])
                inherited_n += 1
            else:
                pending.append(it)
        return inherited_n, pending

    # 噪声点：先质心匹配，匹配不上才 LLM
    noise = members.get(-1, [])
    matched, pending = match_inherit(noise, "噪声")
    log(f"噪声点 {len(noise)} 条: 质心匹配继承 {matched} / LLM 兜底 {len(pending)}")
    if pending:
        for i in range(0, len(pending), 50):
            segs = [(r["review_id"], r["text"][:400]) for r in pending[i:i+50]]
            m = llm_label(segs)
            llm_calls += 1
            llm_labeled += len(m)
            for rid, f in m.items():
                inherited[int(rid)] = f

    return cluster_labels, inherited, llm_calls, llm_labeled, centroids, lab_list


# =====================================================================
# Step 5: 一致率对比
# =====================================================================
def evaluate(items, inherited):
    fields = ["pain_point", "emotion", "body_feature", "usage_scene", "purchase_reason"]
    stats = {}
    for f in fields:
        same = diff = 0
        examples = []
        for it in items:
            gt = it[f]
            pred = inherited.get(it["review_id"], {}).get(f)
            if pred is None:
                continue
            if gt == pred:
                same += 1
            else:
                diff += 1
                if len(examples) < 8:
                    examples.append({"review_id": it["review_id"], "text": it["text"][:120],
                                     "gt": gt, "pred": pred})
        total = same + diff
        stats[f] = {"same": same, "diff": diff, "total": total,
                    "accuracy": round(100.0 * same / total, 1) if total else None,
                    "examples": examples}
    return stats


# =====================================================================
# main
# =====================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="泳衣")
    ap.add_argument("--min-cluster-size", type=int, default=5)
    ap.add_argument("--short-words", type=int, default=1)
    ap.add_argument("--threshold", type=float, default=0.75)
    args = ap.parse_args()
    global SHORT_TEXT_WORDS
    SHORT_TEXT_WORDS = args.short_words

    items = load_ground_truth(args.category)
    log(f"ground truth: {len(items)} 条（{args.category}）")

    # 短文本分离
    short_items = [it for it in items if it["n_words"] < SHORT_TEXT_WORDS]
    long_items = [it for it in items if it["n_words"] >= SHORT_TEXT_WORDS]
    log(f"长文本 {len(long_items)} 条参与聚类 | 短文本 {len(short_items)} 条（<{SHORT_TEXT_WORDS}词）先质心匹配后兜底")

    # 向量化（长文本）
    vecs = vectorize(long_items)
    for it, v in zip(long_items, vecs):
        it["_vec"] = v
    log(f"向量化完成: {vecs.shape}")

    # 聚类
    labels, cl = cluster(vecs, args.min_cluster_size)
    n_clusters = len(set(labels) - {-1})
    n_noise = int((labels == -1).sum())
    log(f"HDBSCAN: {n_clusters} 簇 + {n_noise} 噪声（min_cluster_size={args.min_cluster_size}）")

    # 打标
    cluster_labels, inherited, llm_calls, llm_labeled, centroids, lab_list = \
        label_clusters(long_items, labels, args.min_cluster_size, threshold=args.threshold)

    # 短文本：先质心匹配，匹配不上才 LLM（短文本没有 _vec，需先向量化）
    if short_items:
        svecs = vectorize(short_items)
        for it, v in zip(short_items, svecs):
            it["_vec"] = v
        if lab_list:
            C = np.array([centroids[l] for l in lab_list])
            C = C / np.linalg.norm(C, axis=1, keepdims=True)
            svecs_n = svecs / np.linalg.norm(svecs, axis=1, keepdims=True)
            sim = svecs_n @ C.T
            best = sim.max(axis=1)
            matched_n = 0
            pending = []
            for it, s, bi in zip(short_items, best, sim.argmax(axis=1)):
                if s >= args.threshold:
                    inherited[it["review_id"]] = dict(cluster_labels[lab_list[bi]])
                    matched_n += 1
                else:
                    pending.append(it)
            log(f"短文本 {len(short_items)} 条: 质心匹配继承 {matched_n} / LLM 兜底 {len(pending)}")
        else:
            pending = short_items
            log(f"短文本 {len(short_items)} 条全部 LLM 兜底（无簇）")
        for i in range(0, len(pending), 50):
            segs = [(r["review_id"], r["text"][:400]) for r in pending[i:i+50]]
            m = llm_label(segs)
            llm_calls += 1
            llm_labeled += len(m)
            for rid, f in m.items():
                inherited[int(rid)] = f

    # 评估（只评估被聚类覆盖 + 兜底覆盖到的）
    stats = evaluate(items, inherited)
    covered = sum(s["total"] for s in stats.values()) // 5 if stats else 0

    log("=== 一致率对比（第二版聚类 vs 第一版逐条 LLM）===")
    for f, s in stats.items():
        log(f"  {f:16s} 一致率 {s['accuracy']}%  ({s['same']}/{s['total']})")

    overall = np.mean([s["accuracy"] for s in stats.values() if s["accuracy"] is not None])
    log(f"  平均一致率: {overall:.1f}% | LLM 调用 {llm_calls} 批 / {llm_labeled} 条（原逐条 601 条）")

    # 输出
    out_dir = "/tmp"
    report = {
        "category": args.category, "total": len(items), "covered": covered,
        "n_clusters": n_clusters, "n_noise": n_noise,
        "short_text": len(short_items), "min_cluster_size": args.min_cluster_size,
        "llm_calls_batches": llm_calls, "llm_labeled": llm_labeled,
        "llm_labeled_ratio": round(100.0 * llm_labeled / len(items), 1),
        "stats": stats, "overall_accuracy": round(overall, 1),
        "clusters": {str(k): {"size": len(v), "labels": cluster_labels.get(k)} for k, v in
                     {lab: [it for it in long_items if labels[long_items.index(it)] == lab] for lab in set(labels)}.items()},
    }
    with open(f"{out_dir}/cluster_report_{args.category}.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    md = [f"# 聚类第二版验证报告（{args.category}）", "",
          f"- 数据: {len(items)} 条 | 簇数 {n_clusters} | 噪声 {n_noise} | 短文本 {len(short_items)}",
          f"- LLM 用量: {llm_calls} 批 / {llm_labeled} 条（{report['llm_labeled_ratio']}%）",
          f"- **平均一致率: {overall:.1f}%**（目标 ≥80%）", "",
          "## 分字段一致率", "| 字段 | 一致率 | 同/总 |", "|---|---|---|"]
    for f, s in stats.items():
        md.append(f"| {f} | {s['accuracy']}% | {s['same']}/{s['total']} |")
    md += ["", "## 不一致示例（前8条/字段）"]
    for f, s in stats.items():
        if s["examples"]:
            md.append(f"\n### {f}")
            for e in s["examples"]:
                md.append(f"- [{e['review_id']}] {e['text']}  →  GT={e['gt']} / 聚类={e['pred']}")
    with open(f"{out_dir}/cluster_report_{args.category}.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    log(f"报告: {out_dir}/cluster_report_{args.category}.md")

    passed = overall >= 80
    log(f"结论: {'✅ 达标' if passed else '❌ 未达标'}（{'≥' if passed else '<'}80%）")
    if not passed:
        log("建议: 调小 min_cluster_size / 增大 REPRESENTATIVES / 检查聚类参数")


if __name__ == "__main__":
    main()
