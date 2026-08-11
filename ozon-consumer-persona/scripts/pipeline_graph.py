#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline_graph.py — LangGraph 版画像管线（V2.5，标准姿势）
=====================================================================
线性状态图 + checkpointer 自动断点恢复 + interrupt() 人工审核：

  load → embed → cluster → label → [interrupt 审核] → aggregate → report

LangGraph 关键机制（本次验证）：
1. SqliteSaver 持久化 checkpoint：进程崩溃/重启后，invoke(None) 自动从
   断点继续，**已完成的节点绝不重跑**
2. interrupt()：节点内暂停，产出待审清单；人工确认后 Command(resume=...)
   继续（human-in-the-loop 标准实现）

用法:
  # 全自动跑（无审核，interrupt 直接跳过）
  .venv/bin/python scripts/pipeline_graph.py --category 泳衣 --auto
  # 跑到 review 暂停（interrupt 等人工确认）
  .venv/bin/python scripts/pipeline_graph.py --category 泳衣 --halt-review
  # 重启续跑（自动从断点继续；--auto 模式直接跑完）
  .venv/bin/python scripts/pipeline_graph.py --category 泳衣 --resume
  # 清断点
  .venv/bin/python scripts/pipeline_graph.py --category 泳衣 --reset
=====================================================================
"""
import argparse
import json
import os
import sys
from datetime import datetime
from typing import TypedDict, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt

CHECKPOINT_DB = "/tmp/pipeline_graph_checkpoints.sqlite"
OBSIDIAN_DIR = "{OBSIDIAN_DIR}"

# ---------- Persona 报告常量（与 persona_pipeline 一致） ----------
PAIN_CN = {"size": "尺码偏小/不符", "quality": "质量差", "wrong_item": "发错货/二手", "fading": "褪色掉色",
           "chest_support": "胸部支撑不足", "workmanship": "做工瑕疵", "missing_parts": "缺件漏发",
           "fit_shape": "版型/上身效果", "fabric": "面料问题", "pilling": "勾丝起球",
           "none": "无明显痛点", "other": "其他"}
SCENE_CN = {"vacation": "度假/海滩", "pool": "泳池", "daily": "日常", "sport": "运动游泳",
            "sauna": "桑拿", "gift": "送礼", "unknown": "未知"}
REASON_CN = {"quality": "质量好", "design": "设计好看", "comfort": "舒适", "slimming": "显瘦塑形",
             "support": "支撑好", "fit_shape": "版型合身", "price": "价格合适", "brand": "品牌", "unknown": "未明确"}


class PipelineState(TypedDict, total=False):
    """管线共享状态（TypedDict → 节点返回值按字段合并，不会冲掉其他字段）"""
    category: str
    items: list
    vecs: list
    labels: list
    inherited: dict
    review: list
    review_decision: Any
    stats: dict
    report_path: str
    no_cluster: bool
    min_cluster_size: int


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- 节点 ----------
def node_load(state):
    cat = state["category"]
    log(f"[load] 加载 {cat} 评论（competitor_reviews）...")
    import psycopg2
    from db_config import DB
    conn = psycopg2.connect(**DB)
    with conn.cursor() as cur:
        cur.execute("""SELECT id, sku, score, text FROM competitor_reviews
                       WHERE category=%s ORDER BY id""", (cat,))
        rows = cur.fetchall()
    conn.close()
    items = [{"review_id": r[0], "sku": r[1], "score": r[2],
              "text": (r[3] or "")[:400]} for r in rows]
    log(f"[load] {len(items)} 条")
    return {"items": items}


def node_embed(state):
    log(f"[embed] 向量化 {len(state['items'])} 条...")
    from cluster_pipeline_v2 import vectorize
    items = state["items"]
    vecs = vectorize(items)
    log(f"[embed] 完成 {vecs.shape}")
    return {"vecs": vecs.tolist()}


def node_cluster(state):
    import numpy as np
    import hdbscan
    log("[cluster] 聚类中...")
    vecs = np.array(state["vecs"], dtype=np.float32)
    norm = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    mcs = state.get("min_cluster_size", 5)
    cl = hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=1, metric="euclidean",
                         cluster_selection_method="eom").fit(norm)
    labels = cl.labels_.tolist()
    n_cl = len(set(labels) - {-1})
    n_noise = sum(1 for l in labels if l == -1)
    log(f"[cluster] {n_cl} 簇 + {n_noise} 噪声")
    return {"labels": labels}


def node_label(state):
    import numpy as np
    from cluster_pipeline_v2 import llm_label
    category = state.get("category", "泳衣")
    items = state["items"]
    if state.get("no_cluster"):
        # 语义密集品类（智能手表等）：跳过聚类，全量 LLM 打标
        log(f"[label] no-cluster 模式：{len(items)} 条全量 LLM 打标...")
        inherited = {}
        for i in range(0, len(items), 50):
            segs = [(r["review_id"], r["text"][:400]) for r in items[i:i+50]]
            m = llm_label(segs, category=category)
            for rid, f in m.items():
                inherited[int(rid)] = f
        log(f"[label] 全量打标完成 {len(inherited)} 条")
        return {"inherited": inherited}
    labels = state["labels"]
    vecs = np.array(state["vecs"], dtype=np.float32)
    norm = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
    for it, v in zip(items, norm):
        it["_vec"] = v
    members = {}
    for i, lab in enumerate(labels):
        members.setdefault(lab, []).append(items[i])
    cluster_labels = {}
    for lab, mem in members.items():
        if lab == -1:
            continue
        idx = [i for i, l in enumerate(labels) if l == lab]
        vv = norm[idx]
        c = vv.mean(axis=0)
        c = c / np.linalg.norm(c)
        d = np.linalg.norm(vv - c, axis=1)
        reps = [items[idx[j]] for j in np.argsort(d)[:3]]
        m = llm_label([(r["review_id"], r["text"][:400]) for r in reps], category=category)
        vote = {}
        for f in ("pain_point", "emotion", "body_feature", "usage_scene", "purchase_reason"):
            vals = [m.get(str(r["review_id"]), {}).get(f) for r in reps]
            vals = [v for v in vals if v and v != "unknown"]
            vote[f] = max(set(vals), key=vals.count) if vals else "unknown"
        cluster_labels[lab] = vote
    # 簇成员继承标签；噪声点（-1）标记待 LLM 兜底
    inherited = {}
    pending_noise = []
    for lab, mem in members.items():
        if lab == -1:
            pending_noise.extend(mem)
            continue
        for it in mem:
            inherited[it["review_id"]] = dict(cluster_labels[lab])
    # 噪声点 LLM 兜底（逐条打标）
    if pending_noise:
        log(f"[label] 噪声点 {len(pending_noise)} 条 LLM 兜底...")
        for i in range(0, len(pending_noise), 50):
            segs = [(r["review_id"], r["text"][:400]) for r in pending_noise[i:i+50]]
            m = llm_label(segs, category=category)
            for rid, f in m.items():
                inherited[int(rid)] = f
    log(f"[label] {len(cluster_labels)} 簇打标 + 噪声兜底，共 {len(inherited)} 条")
    return {"inherited": inherited}


def node_review(state):
    """human-in-the-loop：interrupt() 暂停，产出待审清单等人工确认"""
    from collections import Counter
    import numpy as np
    labels = state["labels"]
    items = state["items"]
    inherited = state.get("inherited", {})
    review_items = []
    for lab in set(labels):
        if lab == -1:
            continue
        idx = np.where(np.array(labels) == lab)[0]
        if len(idx) < 3:
            continue
        pts = [inherited.get(items[i]["review_id"], {}).get("pain_point", "other") for i in idx]
        c = Counter(pts)
        top_ratio = c.most_common(1)[0][1] / len(idx)
        if top_ratio < 0.6:
            review_items.append({
                "cluster": int(lab), "size": int(len(idx)),
                "top_pain": c.most_common(1)[0][0], "top_ratio": round(top_ratio, 2),
                "samples": [{"review_id": items[i]["review_id"], "text": items[i]["text"][:150]} for i in idx[:2]],
            })
    log(f"[review] 低置信度簇 {len(review_items)} 个 → 暂停等待人工审核")
    # 写审核清单到文件（人工可查看/编辑）
    cat = state["category"]
    review_path = f"/tmp/pipeline_review_{cat}.json"
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(review_items, f, ensure_ascii=False, indent=2)
    # interrupt：暂停图执行，把审核清单给外部；resume 值 = 人工确认结果
    decision = interrupt({"action": "review_clusters", "items": review_items,
                          "review_path": review_path})
    log(f"[review] 人工确认: {decision}")
    return {"review": review_items, "review_decision": decision}


def node_aggregate(state):
    """从 items + inherited（内存标签）算分布，结构与 persona_pipeline.aggregate() 一致"""
    from collections import Counter
    items = state["items"]
    inherited = state.get("inherited", {})
    # 把标签合并回 item
    for it in items:
        lab = inherited.get(it["review_id"], {})
        it["pain_point"] = lab.get("pain_point", "other")
        it["purchase_reason"] = lab.get("purchase_reason", "unknown")
        it["usage_scene"] = lab.get("usage_scene", "unknown")
        it["body_feature"] = lab.get("body_feature", "unknown")

    def dist(items, key, cond=None):
        c = Counter()
        for it in items:
            if cond and not cond(it):
                continue
            v = it.get(key, "unknown")
            c[v] += 1
        return c

    pain = dist(items, "pain_point", lambda it: (it.get("score") or 0) <= 3)
    motivation = dist(items, "purchase_reason", lambda it: (it.get("score") or 0) >= 4)
    scenes = dist(items, "usage_scene", lambda it: it.get("usage_scene") != "unknown")
    body = dist(items, "body_feature", lambda it: it.get("body_feature") != "unknown")

    def pct(c):
        total = sum(c.values()) or 1
        return [(k, v, round(100.0 * v / total, 1)) for k, v in c.most_common()]

    gift_kw = ("муж", "папа", "жене", "подарок", "дочь", "дочери", "мам", "бабушк", "двойня")
    plus_kw = ("больш", "полн")
    text_all = " ".join((it.get("text") or "").lower() for it in items)
    gift_signals = sum(1 for it in items if any(k in (it.get("text") or "").lower() for k in gift_kw))
    plus_signals = sum(1 for it in items if any(k in (it.get("text") or "").lower() for k in plus_kw))

    agg = {
        "total_reviews": len(items), "total_analyzed": len(inherited),
        "pain": pct(pain), "motivation": pct(motivation),
        "scenes": pct(scenes), "body": pct(body),
        "gift_signals": gift_signals, "plus_signals": plus_signals,
    }
    log(f"[aggregate] 痛点TOP5: {agg['pain'][:5]}")
    return {"stats": agg}


def build_personas(agg: dict, category: str = "泳衣") -> list[dict]:
    """按品类配置生成 Persona（见 category_config.py）"""
    from category_config import get_config
    cfg = get_config(category)
    return cfg["build_personas"](agg)


def write_obsidian(category: str, agg: dict, personas: list[dict], doc_name: str, no_cluster=False):
    from datetime import date
    from category_config import get_config
    cfg = get_config(category)
    PAIN_CN, SCENE_CN, REASON_CN = cfg["PAIN_CN"], cfg["SCENE_CN"], cfg["REASON_CN"]
    landing_points = cfg["landing_points"](agg)
    pain_lines = "\n".join(
        f"| {i} | **{PAIN_CN.get(k, k)}** | **{p}%** | 语义分析 {agg['total_analyzed']} 条差评 |"
        for i, (k, c, p) in enumerate(agg["pain"][:8], 1))
    scene_lines = "、".join(f"{SCENE_CN.get(k, k)} {p}%" for k, c, p in agg["scenes"][:4])
    mot_lines = " > ".join(f"{REASON_CN.get(k, k)} {p}%" for k, c, p in agg["motivation"][:5])
    persona_blocks = []
    for p in personas:
        pains = "；".join(f"{a} {b}%" for a, b in p["pain"])
        persona_blocks.append(f"""### {p['id']} {p['name']}（~{p['percentage']:.0f}%）
- 年龄 {p['age']} | 身材 {p['body']} | 场景 {p['scene']}
- 痛点：{pains}
- 搜索词：{'、'.join(p['keywords'])}
- 主图：{p['visual']} ｜ 广告：{'；'.join(p['ad'])}""")
    doc = f"""# 26-{category}消费人群画像（{date.today()} 图引擎版）

> 生成: pipeline_graph.py（LangGraph）｜ 数据: {agg['total_reviews']} 评论 / {agg['total_analyzed']} 条 LLM 语义分析
> 方法: bge-m3 向量化 → HDBSCAN 聚类 → 每簇 3 代表 LLM 打标 → 继承 + 噪声兜底（--no-cluster 模式: 全量 LLM 打标）

## 一、量化痛点排名（差评）
| # | 痛点 | 占比 | 说明 |
|---|---|---|---|
{pain_lines}

## 二、购买动机排名（好评）
{mot_lines}

## 三、场景分布
{scene_lines}

## 四、Persona 聚类（{len(personas)} 个）
{chr(10).join(persona_blocks)}

## 五、落地要点
{chr(10).join('1. ' + p if i == 0 else f'{i+1}. ' + p for i, p in enumerate(landing_points))}

## 关联
- → [[25-{店铺}消费人群画像]] ｜ SOP《消费者画像分析 SOP V1.0》
"""
    os.makedirs(OBSIDIAN_DIR, exist_ok=True)
    path = os.path.join(OBSIDIAN_DIR, doc_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    log(f"Obsidian 已写: {path}")


def node_report(state):
    """Persona 生成 + Obsidian 报告（纯本地逻辑，无外部依赖）"""
    cat = state["category"]
    agg = state["stats"]
    personas = build_personas(agg, category=cat)
    doc_name = f"26-{cat}消费人群画像.md"
    try:
        write_obsidian(cat, agg, personas, doc_name, no_cluster=state.get("no_cluster"))
    except Exception as e:
        log(f"[report] Obsidian 写入失败: {type(e).__name__}: {e}")
    import json as _json
    tmp = f"/tmp/pipeline_graph_{cat}.json"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump({
            "category": cat, "stats": agg, "personas": personas,
            "review": state.get("review", []),
            "n_items": len(state["items"]),
            "clusters": len(set(state["labels"]) - {-1}),
        }, f, ensure_ascii=False, indent=2, default=str)
    log(f"[report] 临时数据 {tmp}")
    return {"report_path": tmp}


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("load", node_load)
    g.add_node("embed", node_embed)
    g.add_node("cluster", node_cluster)
    g.add_node("label", node_label)
    g.add_node("review", node_review)
    g.add_node("aggregate", node_aggregate)
    g.add_node("report", node_report)
    g.add_edge(START, "load")
    g.add_edge("load", "embed")
    g.add_edge("embed", "cluster")
    g.add_edge("cluster", "label")
    g.add_edge("label", "review")
    g.add_edge("review", "aggregate")
    g.add_edge("aggregate", "report")
    g.add_edge("report", END)
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default="泳衣")
    ap.add_argument("--auto", action="store_true", help="自动模式：interrupt 直接 resume approved")
    ap.add_argument("--resume", action="store_true", help="从断点续跑（interrupt 处继续）")
    ap.add_argument("--reset", action="store_true", help="清 checkpoint")
    ap.add_argument("--min-cluster-size", type=int, default=0, help="HDBSCAN 最小簇大小，0=默认5")
    ap.add_argument("--no-cluster", action="store_true", help="跳过聚类，全量 LLM 打标（语义密集品类用）")
    args = ap.parse_args()

    thread_id = f"pipeline-{args.category}"
    if args.reset and os.path.exists(CHECKPOINT_DB):
        os.remove(CHECKPOINT_DB)
        log("[reset] 已清 checkpoint")

    with SqliteSaver.from_conn_string(CHECKPOINT_DB) as saver:
        graph = build_graph().compile(checkpointer=saver)
        config = {"configurable": {"thread_id": thread_id}}

        snap = graph.get_state(config)
        cur = snap.values if snap.values else {}
        pending = snap.next if snap else ()
        log(f"[state] next={list(pending)} items={len(cur.get('items', []))}")

        def run_once(payload, label):
            """执行一轮；若 interrupt 暂停则决定是否继续"""
            try:
                result = graph.invoke(payload, config=config)
                snap_after = graph.get_state(config)
                if snap_after.next:
                    # interrupt 暂停：next 非空
                    log(f"⏸ {label} 在 review 暂停（human-in-the-loop），待审清单: /tmp/pipeline_review_{args.category}.json")
                    if args.auto or args.resume:
                        log("   [auto] resume approved 继续...")
                        run_once(Command(resume="approved"), "续跑")
                    else:
                        log("   手动续跑: 加 --resume（resume 值默认 approved）")
                else:
                    log(f"✅ {label} 执行完成")
                return True
            except Exception as e:
                if "Interrupt" in type(e).__name__:
                    log(f"⏸ {label} 在 review 暂停（human-in-the-loop）")
                    if args.auto or args.resume:
                        run_once(Command(resume="approved"), "续跑")
                    return True
                raise

        if args.resume:
            if pending:
                run_once(Command(resume="approved"), "续跑")
            else:
                log("[resume] 无未完成执行")
        else:
            init = {"category": args.category}
            if args.min_cluster_size:
                init["min_cluster_size"] = args.min_cluster_size
            if args.no_cluster:
                init["no_cluster"] = True
            run_once(init, "执行")

        snap2 = graph.get_state(config)
        log(f"最终 next={list(snap2.next)}")


if __name__ == "__main__":
    main()
