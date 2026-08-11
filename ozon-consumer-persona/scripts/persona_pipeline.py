#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
persona_pipeline.py — 消费者画像分析全流程自动化（V1）
=====================================================================
链路: 采集差评/好评 → 规则清洗 → LLM 批量语义分析 → SQL 量化聚合
      → Persona 聚类 → 报告（/tmp 临时 + Obsidian 归档 + 可选 Dify）

用法（必须用 MCP venv 的 python，因采集依赖 ozon-connector/mcp_core）:
  {MCP_VENV_PYTHON} \
      scripts/persona_pipeline.py --category 泳衣 \
      --skus "1853242673,1419923538,1506545968" --bad 600 --good 200

分步执行（幂等可续）:
  --fetch-only    只采集评论落库（competitor_reviews）
  --analyze-only  只清洗+LLM分析（review_analysis，已有分析跳过）
  --report-only   只聚合+Persona+报告（Obsidian）
=====================================================================
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_config import DB

# ---------- 采集依赖（ozon-connector，需 MCP venv） ----------
sys.path.insert(0, "{OZON_CONNECTOR_SRC}")
from ozon_connector.server import (  # noqa: E402
    _fetch_composer, _parse_review_item, _safe_review_page_path,
    _canonical_product_path_from_input,
)

# ---------- 配置 ----------
OBSIDIAN_DIR = "{OBSIDIAN_DIR}"
TMP_REPORT = "/tmp/persona_report"
MAX_PAGES = 14
STOP_EMPTY = 2
LOGISTICS_WORDS = [
    "доставка", "курьер", "упаковка", "продавец", "магазин", "заказ", "пришёл быстро",
    "пришел быстро", "оформил", "оформила", "пункт выдачи", "ПВЗ", "отправ", "получил",
    "получила", "спасибо за доставку", "срок", "быстро приш",
]
MODEL = "deepseek-chat"
API_URL = "https://api.deepseek.com/chat/completions"
KEY_FILE = "{MODELS_JSON}"
BATCH = 50
CONCURRENCY = 3


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def get_api_key():
    with open(KEY_FILE) as f:
        return json.load(f)["providers"]["deepseek"]["apiKey"]


def db_conn():
    return psycopg2.connect(**DB)


def json_loads(s):
    return json.loads(s)


def _widget(widgets: dict, prefix: str) -> dict:
    for k, v in widgets.items():
        if k.startswith(prefix):
            try:
                parsed = json_loads(v) if isinstance(v, str) else v
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {}


# =====================================================================
# Step 1: 采集评论（差评 score_asc / 好评 score_desc）
# =====================================================================
async def _fetch_reviews_page(sku: str, sort: str) -> list[dict]:
    canonical, err = _canonical_product_path_from_input(sku)
    if err:
        raise RuntimeError(f"canonical path error: {err}")
    collected, seen, pages, empty = [], set(), 0, 0
    next_path = f"/product/{sku}/reviews/?sort={sort}"
    while next_path and pages < MAX_PAGES:
        status, body, tier = await _fetch_composer(next_path, None)
        pages += 1
        if status != 200:
            log(f"  page {pages}: HTTP {status} — 停止")
            break
        try:
            payload = json_loads(body)
        except Exception as exc:
            log(f"  page {pages}: JSON 解析失败 {exc}")
            break
        list_w = _widget(payload.get("widgetStates") or {}, "webListReviews")
        page_hit = 0
        for r in list_w.get("reviews") if isinstance(list_w.get("reviews"), list) else []:
            if not isinstance(r, dict):
                continue
            u = str(r.get("uuid")) if r.get("uuid") else ""
            if u and u in seen:
                continue
            if u:
                seen.add(u)
            item = _parse_review_item(r)
            if not item:
                continue
            collected.append(item)
            page_hit += 1
        if page_hit == 0:
            empty += 1
            if empty >= STOP_EMPTY:
                break
        else:
            empty = 0
        paging = list_w.get("paging") or {}
        nb = paging.get("nextButton")
        if nb:
            cand = _safe_review_page_path(sku, nb)
            next_path = cand if cand else None
            if not cand:
                break
        else:
            next_path = None
    return collected


def fetch_reviews(skus: list[int], kind: str, target: int, category: str, fetch_date: date):
    """kind: bad(score<=3, sort=score_asc) / good(score>=4, sort=score_desc)"""
    sort = "score_asc" if kind == "bad" else "score_desc"
    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT sku, score, text FROM competitor_reviews WHERE category=%s", (category,))
        existing = {(r[0], r[1], (r[2] or "").strip()) for r in cur.fetchall()}
    total = 0
    for sku in skus:
        log(f"采集[{kind}] SKU {sku} ...")
        items = asyncio.run(_fetch_reviews_page(str(sku), sort))
        rows = []
        for it in items:
            full = (it.get("text") or "").strip()
            if not full:
                full = (it.get("positive") or "").strip() or (it.get("negative") or "").strip()
            score = int(it.get("score") or 0)
            if kind == "bad" and score > 3:
                continue
            if kind == "good" and score < 4:
                continue
            key = (sku, score, full)
            if not full or key in existing:
                continue
            rows.append((sku, score, full, it.get("author"), it.get("date"),
                         "ozon_reviews_front_good" if kind == "good" else "ozon_reviews_front"))
            existing.add(key)
            if len(rows) >= target:
                break
        with conn.cursor() as cur:
            for sku, score, text, author, rdate, src in rows:
                cur.execute(
                    """INSERT INTO competitor_reviews
                       (platform, fetch_date, sku, score, text, author, review_date, category, source)
                       VALUES ('ozon',%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (platform, fetch_date, sku, text) DO NOTHING""",
                    (fetch_date, sku, score, text, author, rdate, category, src))
        conn.commit()
        total += len(rows)
        log(f"  ✓ SKU {sku} 新入库 {len(rows)} 条")
    conn.close()
    log(f"采集[{kind}] 完成，新入库 {total} 条")


# =====================================================================
# Step 2: LLM 批量语义分析
# =====================================================================
PROMPT_TMPL = """你是俄罗斯电商消费者画像分析师。分析以下{kind}评论（俄语），逐条提取结构化信息。

严格输出 JSON 数组，每条格式：
{{"id": 序号, "pain_point": "枚举值", "emotion": "枚举值", "body_feature": "枚举值", "usage_scene": "枚举值", "purchase_reason": "枚举值"}}

枚举说明：
- pain_point: size=尺码问题, chest_support=胸部支撑, missing_parts=缺件漏发, wrong_item=发错货/二手, quality=质量差, pilling=勾丝起球, fading=褪色, workmanship=做工瑕疵, fit_shape=版型/上身效果, fabric=面料, none=无明显痛点, other=其他
- emotion: positive=满意, neutral=一般, negative=失望, angry=愤怒
- body_feature: slim=苗条, normal=普通, plus_size=丰满/大码, big_bust=大胸, unknown=无法判断
- usage_scene: pool=泳池, vacation=度假/海滩, sport=运动游泳, sauna=桑拿, gift=送礼, daily=日常, unknown=无法判断
- purchase_reason({kind2}才填，{kind3}填"unknown"): slimming=显瘦塑形, comfort=舒适, design=设计好看, quality=质量好, price=价格, support=支撑好, brand=品牌, unknown=无

只输出 JSON，不要任何解释。无法判断的字段用 unknown。

评论列表（每条以 [序号] 开头，输出时 id 必须严格等于该序号，例如第一条 id=1）：
{items}"""


def call_api(messages, retries=3):
    body = json.dumps({
        "model": MODEL, "messages": messages, "temperature": 0.1, "max_tokens": 6000,
    }).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=body, headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {get_api_key()}"})
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


def analyze_batch(segments, kind):
    lines = "\n".join(f"[{i+1}] {t}" for i, t in segments)
    kind2 = "好评" if kind == "good" else "unknown"
    kind3 = "差评" if kind == "good" else "好评"
    prompt = PROMPT_TMPL.format(kind="好评" if kind == "good" else "差评", items=lines, kind2=kind2, kind3=kind3)
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


def is_logistics(text):
    low = (text or "").lower()
    return any(w in low for w in LOGISTICS_WORDS)


def analyze_reviews(category: str):
    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, sku, score, text FROM competitor_reviews WHERE category=%s ORDER BY id", (category,))
        rows = cur.fetchall()
        cur.execute("SELECT review_id FROM review_analysis WHERE category=%s", (category,))
        analyzed = {r[0] for r in cur.fetchall()}
    conn.close()
    logistics = [r for r in rows if is_logistics(r[3] or "")]
    pending = [r for r in rows if not is_logistics(r[3] or "") and r[0] not in analyzed]
    log(f"共 {len(rows)} 条 | 物流过滤 {len(logistics)} | 待分析 {len(pending)}")

    groups = []
    for kind in ("good", "bad"):
        pool = [r for r in pending if (r[2] or 0) >= 4] if kind == "good" else [r for r in pending if (r[2] or 0) <= 3]
        for i in range(0, len(pool), BATCH):
            groups.append((kind, pool[i:i + BATCH]))
    if not groups:
        log("无待分析评论")
        return

    results = {}
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(analyze_batch, [(r[0], (r[3] or "")[:400]) for r in g], kind): (kind, g) for kind, g in groups}
        for fut in futs:
            kind, g = futs[fut]
            try:
                res = fut.result()
                results.update(res)
                log(f"  [{kind}] 批完成 {len(res)}/{len(g)}")
            except Exception as e:
                log(f"  [{kind}] 批失败: {e}")

    conn = db_conn()
    inserted = 0
    with conn.cursor() as cur:
        for rid, f in results.items():
            r = next((r for r in rows if r[0] == int(rid)), None)
            if not r:
                continue
            cur.execute("""
                INSERT INTO review_analysis
                (review_id, category, sku, score, text, pain_point, emotion, body_feature,
                 usage_scene, purchase_reason, confidence)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (review_id, category) DO UPDATE SET
                  pain_point=EXCLUDED.pain_point, emotion=EXCLUDED.emotion,
                  body_feature=EXCLUDED.body_feature, usage_scene=EXCLUDED.usage_scene,
                  purchase_reason=EXCLUDED.purchase_reason
            """, (int(rid), category, r[1], r[2], r[3], f.get("pain_point"), f.get("emotion"),
                  f.get("body_feature"), f.get("usage_scene"), f.get("purchase_reason"), 0.8))
            inserted += 1
    conn.commit()
    conn.close()
    log(f"LLM 分析落库 {inserted} 条 → review_analysis")


# =====================================================================
# Step 3: 量化聚合 + Persona
# =====================================================================
PAIN_CN = {"size": "尺码偏小/不符", "quality": "质量差", "wrong_item": "发错货/二手", "fading": "褪色掉色",
           "chest_support": "胸部支撑不足", "workmanship": "做工瑕疵", "missing_parts": "缺件漏发",
           "fit_shape": "版型/上身效果", "fabric": "面料问题", "pilling": "勾丝起球",
           "none": "无明显痛点", "other": "其他"}
SCENE_CN = {"vacation": "度假/海滩", "pool": "泳池", "daily": "日常", "sport": "运动游泳",
            "sauna": "桑拿", "gift": "送礼", "unknown": "未知"}
REASON_CN = {"quality": "质量好", "design": "设计好看", "comfort": "舒适", "slimming": "显瘦塑形",
             "support": "支撑好", "fit_shape": "版型合身", "price": "价格合适", "brand": "品牌", "unknown": "未明确"}


def aggregate(category: str) -> dict:
    conn = db_conn()
    cur = conn.cursor()

    def dist(col, table, extra=""):
        cur.execute(f"SELECT {col}, COUNT(*) FROM {table} WHERE category=%s {extra} GROUP BY {col} ORDER BY 2 DESC", (category,))
        return cur.fetchall()

    pain = dist("pain_point", "review_analysis", "AND score<=3")
    motivation = dist("purchase_reason", "review_analysis", "AND score>=4")
    scenes = dist("usage_scene", "review_analysis", "AND usage_scene!='unknown'")
    body = dist("body_feature", "review_analysis", "AND body_feature!='unknown'")

    cur.execute("SELECT COUNT(*) FROM competitor_reviews WHERE category=%s", (category,))
    total_reviews = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM review_analysis WHERE category=%s", (category,))
    total_analyzed = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM competitor_reviews
                   WHERE category=%s AND (text ILIKE '%%муж%%' OR text ILIKE '%%папа%%' OR text ILIKE '%%жене%%'
                     OR text ILIKE '%%подарок%%' OR text ILIKE '%%дочь%%' OR text ILIKE '%%дочери%%'
                     OR text ILIKE '%%мам%%' OR text ILIKE '%%бабушк%%' OR text ILIKE '%%двойня%%')""", (category,))
    gift_signals = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM competitor_reviews WHERE category=%s
                   AND (text ILIKE '%%больш%%' OR text ILIKE '%%полн%%')""", (category,))
    plus_signals = cur.fetchone()[0]
    conn.close()

    def pct(lst):
        total = sum(c for _, c in lst) or 1
        return [(k, c, round(100.0 * c / total, 1)) for k, c in lst]

    return {
        "total_reviews": total_reviews, "total_analyzed": total_analyzed,
        "pain": pct(pain), "motivation": pct(motivation), "scenes": pct(scenes), "body": pct(body),
        "gift_signals": gift_signals, "plus_signals": plus_signals,
    }


def build_personas(agg: dict) -> list[dict]:
    """按量化信号生成 Persona（规则模板，数据驱动）"""
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    scene_map = {k: pct for k, c, pct in agg["scenes"]}
    total = agg["total_reviews"] or 1
    plus_pct = round(100.0 * agg["plus_signals"] / total, 1)
    gift_pct = round(100.0 * agg["gift_signals"] / total, 1)
    chest = pain_map.get("chest_support", 0)
    pool = scene_map.get("pool", 0)
    vacation = scene_map.get("vacation", 0)

    personas = []
    # P1 丰满度假（大码提及>5% 或 尺码痛点>15%）
    if plus_pct > 5 or pain_map.get("size", 0) > 15:
        personas.append({
            "id": "P1", "name": "成熟丰满度假女性（Plus Size Vacationer）",
            "percentage": round(45 + (plus_pct - 10) * 0.5, 0) if plus_pct > 10 else 40,
            "age": "35-55", "gender": "女", "body": f"丰满/大码（大码提及 {plus_pct}%）",
            "scene": f"度假/海滩（{vacation}%）+ 出行前急购",
            "pain": [("尺码偏小/不符", pain_map.get("size", 0)), ("胸部支撑不足", chest)],
            "keywords": ["купальник женский больших размеров", "утягивающий", "высокой посадкой"],
            "visual": "丰满真人模特 + 遮腹设计展示 + 身高体重尺码表",
            "ad": ["大码也能美（模特同身材）", "显瘦遮肚前后对比", "尺码诚实承诺"],
        })
    # P2 泳池常客（泳池场景>10%）
    if pool > 10:
        personas.append({
            "id": "P2", "name": "泳池常客女性（Pool Regular）",
            "percentage": round(pool, 0),
            "age": "45-65", "gender": "女", "body": "普通/微胖，多为连体款",
            "scene": f"泳池/水上乐园（{pool}%）每周2-3次",
            "pain": [("褪色掉色", pain_map.get("fading", 0)), ("质量差", pain_map.get("quality", 0))],
            "keywords": ["купальник слитный женский", "для бассейна"],
            "visual": "素色/黑色连体 + 面料耐氯承诺 + 机洗不变形",
            "ad": ["每周游泳不褪色", "耐氯面料实测", "运动游泳专业款"],
        })
    # P3 大胸刚需（胸部痛点>5%）
    if chest > 5:
        personas.append({
            "id": "P3", "name": "大胸支撑刚需人群（Big Bust）",
            "percentage": round(chest, 0),
            "age": "30-45", "gender": "女", "body": "大胸（D+杯）",
            "scene": "泳池+度假双场景",
            "pain": [("胸部支撑不足", chest), ("版型", pain_map.get("fit_shape", 0))],
            "keywords": ["лиф купальный женский", "с поддержкой"],
            "visual": "带钢圈/宽肩带设计特写 + 罩杯对照表",
            "ad": ["大胸也能稳稳托住", "杯型不塌不空", "游泳不掉肩带"],
        })
    # P4 代买送礼（信号>2%）
    if gift_pct > 2:
        personas.append({
            "id": "P4", "name": "代买/送礼人群（Gift Buyer）",
            "percentage": round(gift_pct * 3, 0) if gift_pct * 3 < 15 else 15,
            "age": "30-55", "gender": "男/子女（代买）", "body": "无（给妻子/母亲/女儿买）",
            "scene": "送礼、紧急补买",
            "pain": [("发错货/二手", pain_map.get("wrong_item", 0)), ("缺件漏发", pain_map.get("missing_parts", 0))],
            "keywords": ["купальник женский", "подарок"],
            "visual": "完整套装展示（含泳裤）+ 礼品包装 + 尺码速查",
            "ad": ["给她的完美礼物", "套装齐全不踩雷", "快速尺码指南"],
        })
    if not personas:  # 兜底
        personas.append({
            "id": "P1", "name": "核心购买人群", "percentage": 100, "age": "未知", "gender": "女",
            "body": "未知", "scene": "未知", "pain": [("尺码问题", pain_map.get("size", 0))],
            "keywords": ["купальник женский"], "visual": "产品实拍 + 尺码表", "ad": ["通用卖点"],
        })
    return personas


# =====================================================================
# Step 4: 报告生成（Obsidian + /tmp）
# =====================================================================
def write_obsidian(category: str, agg: dict, personas: list[dict], doc_name: str):
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
    doc = f"""# 26-{category}消费人群画像（{date.today()} 自动化版）

> 生成: persona_pipeline.py ｜ 数据: {agg['total_reviews']} 评论 / {agg['total_analyzed']} 条 LLM 语义分析
> 方法: 批量 DeepSeek（50条/批）→ SQL 量化聚合 → Persona 规则聚类

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
1. 尺码诚实 + 身高体重对照表（第一痛点 {agg['pain'][0][2] if agg['pain'] else 0}%）
2. 卖点按 Persona 打（见各卡主图/广告方向）
3. 品控红线：套装完整 + 标签齐全 + 质检

## 关联
- → [[25-{店铺}消费人群画像]] ｜ SOP《消费者画像分析 SOP V1.0》
"""
    os.makedirs(OBSIDIAN_DIR, exist_ok=True)
    path = os.path.join(OBSIDIAN_DIR, doc_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    log(f"Obsidian 已写: {path}")


def write_tmp(category: str, agg: dict, personas: list[dict]):
    out = os.path.join(TMP_REPORT, category.replace("/", "_") + "_" + date.today().isoformat())
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "agg.json"), "w", encoding="utf-8") as f:
        json.dump({"agg": agg, "personas": personas}, f, ensure_ascii=False, indent=2)
    log(f"临时数据: {out}/agg.json")


def sync_dify(doc_path: str, dataset: str):
    scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    login = subprocess.run([sys.executable, os.path.join(scripts, "dify_login.py")], capture_output=True, text=True)
    if login.returncode != 0:
        log("Dify 登录失败，跳过同步")
        return
    r = subprocess.run([sys.executable, os.path.join(scripts, "dify_sync_files.py"),
                        "--dataset", dataset, "--file", doc_path], capture_output=True, text=True)
    log(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "Dify 同步完成")


# =====================================================================
# main
# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="消费者画像全流程自动化 V1")
    ap.add_argument("--category", required=True, help="品类，如 泳衣")
    ap.add_argument("--skus", default="", help="竞品 SKU 逗号分隔（采集用）")
    ap.add_argument("--bad", type=int, default=600, help="差评目标条数")
    ap.add_argument("--good", type=int, default=200, help="好评目标条数")
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--graph", action="store_true", help="用 LangGraph 图引擎（聚类先行 + 断点续跑 + 人工审核）")
    ap.add_argument("--graph-auto", action="store_true", help="图引擎自动模式（审核直接 approved）")
    ap.add_argument("--graph-resume", action="store_true", help="图引擎从断点续跑")
    ap.add_argument("--obsidian-name", default="", help="Obsidian 文档名，默认 26-<品类>消费人群画像.md")
    ap.add_argument("--dify-dataset", default="b8b8b72b-0792-45a6-80ed-dc53a69e5184", help="Dify ②库")
    ap.add_argument("--no-dify", action="store_true", help="跳过 Dify 同步")
    args = ap.parse_args()

    # ===== 图引擎模式（LangGraph：聚类先行 + 断点 + 审核） =====
    if args.graph or args.graph_auto or args.graph_resume:
        import pipeline_graph as pg
        # 透传参数：先清 checkpoint（除非 resume）
        extra = []
        if args.graph_resume:
            extra.append("--resume")
        elif args.graph:
            extra.append("--reset")
        elif args.graph_auto:
            extra.append("--reset")
            extra.append("--auto")
        cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline_graph.py"),
               "--category", args.category] + extra
        log(f"启动图引擎: {' '.join(cmd)}")
        r = subprocess.run(cmd)
        sys.exit(r.returncode)

    doc_name = args.obsidian_name or f"26-{args.category}消费人群画像.md"
    fetch_date = date.today()
    skus = [int(s) for s in args.skus.split(",") if s.strip()] if args.skus else []

    if not (args.fetch_only or args.analyze_only or args.report_only):
        args.fetch_only = args.analyze_only = args.report_only = True

    if args.fetch_only:
        if not skus:
            log("采集需要 --skus"); return
        fetch_reviews(skus, "bad", args.bad, args.category, fetch_date)
        fetch_reviews(skus, "good", args.good, args.category, fetch_date)

    if args.analyze_only:
        analyze_reviews(args.category)

    if args.report_only:
        agg = aggregate(args.category)
        personas = build_personas(agg)
        write_obsidian(args.category, agg, personas, doc_name)
        write_tmp(args.category, agg, personas)
        if not args.no_dify:
            sync_dify(os.path.join(OBSIDIAN_DIR, doc_name), args.dify_dataset)

    log("pipeline 完成 ✅")


if __name__ == "__main__":
    main()
