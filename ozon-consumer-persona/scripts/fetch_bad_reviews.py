#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
竞品差评抓取（通用版，1-2 星，score_asc 翻页）→ competitor_reviews 表
用法: CHROME_CDP_PORT=9223 .venv/bin/python scripts/fetch_bad_reviews.py \
      --category 智能手表 --skus "3972075096,4115126740" --target 300
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import date

import psycopg2

sys.path.insert(0, "{OZON_CONNECTOR_SRC}")
from ozon_connector.server import (
    _fetch_composer,
    _parse_review_item,
    _safe_review_page_path,
    _canonical_product_path_from_input,
)

sys.path.insert(0, "{WORKSPACE}/scripts")
from db_config import DB

MAX_PAGES = 15
STOP_EMPTY_PAGES = 2


def log(msg):
    print(msg, flush=True)


def _widget(widgets: dict, prefix: str) -> dict:
    for k, v in widgets.items():
        if k.startswith(prefix):
            try:
                parsed = json.loads(v) if isinstance(v, str) else v
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {}


def db_conn():
    return psycopg2.connect(**DB)


async def fetch_bad(sku: str, limit: int) -> list[dict]:
    canonical, err = _canonical_product_path_from_input(sku)
    if err:
        raise RuntimeError(f"canonical path error: {err}")
    next_path = f"/product/{sku}/reviews/?sort=score_asc"
    collected = []
    seen = set()
    pages = 0
    empty_streak = 0
    while next_path and pages < MAX_PAGES and len(collected) < limit:
        status, body, tier = await _fetch_composer(next_path, None)
        pages += 1
        if status != 200:
            log(f"  page {pages}: HTTP {status} — 停止")
            break
        try:
            payload = json.loads(body)
        except Exception as exc:
            log(f"  page {pages}: JSON 解析失败: {exc}")
            break
        list_w = _widget(payload.get("widgetStates") or {}, "webListReviews")
        page_bad = 0
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
            score = int(item.get("score") or 0)
            if score <= 3:
                page_bad += 1
                collected.append(item)
                if len(collected) >= limit:
                    break
        log(f"  page {pages}: +{page_bad} 条差评 (累计 {len(collected)})")
        if page_bad == 0:
            empty_streak += 1
            if empty_streak >= STOP_EMPTY_PAGES:
                log("  连续无差评，停止")
                break
        else:
            empty_streak = 0
        paging = list_w.get("paging") or {}
        nb = paging.get("nextButton")
        if nb and len(collected) < limit:
            next_path = _safe_review_page_path(sku, nb)
            if not next_path:
                log("  nextButton 无效，停止")
                break
        else:
            next_path = None
    return collected


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True)
    ap.add_argument("--skus", required=True, help="逗号分隔 SKU")
    ap.add_argument("--target", type=int, default=300, help="每 SKU 目标差评数")
    ap.add_argument("--fetch-date", default="", help="YYYY-MM-DD，默认今天")
    args = ap.parse_args()

    skus = [s.strip() for s in args.skus.split(",") if s.strip()]
    fetch_date = date.fromisoformat(args.fetch_date) if args.fetch_date else date.today()
    os.environ.setdefault("CHROME_CDP_PORT", "9223")

    conn = db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT sku, score, text FROM competitor_reviews WHERE category=%s AND score<=3", (args.category,))
        existing = {(r[0], r[1], (r[2] or "").strip()) for r in cur.fetchall()}
    log(f"[{args.category}] 已有差评 {len(existing)} 条 | SKU: {skus} | 每 SKU 目标 {args.target}")

    total = 0
    for sku in skus:
        log(f"抓取 {sku} 差评...")
        items = await fetch_bad(sku, args.target)
        rows = []
        for it in items:
            full = (it.get("text") or "").strip()
            if not full:
                full = (it.get("positive") or "").strip() or (it.get("negative") or "").strip()
            key = (int(sku), it.get("score"), full.strip())
            if not full or key in existing:
                continue
            rows.append({
                "platform": "ozon", "fetch_date": fetch_date, "sku": int(sku),
                "score": it.get("score"), "text": full, "author": it.get("author"),
                "review_date": it.get("date"), "category": args.category,
                "source": "ozon_reviews_front_bad",
            })
            existing.add(key)
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """INSERT INTO competitor_reviews
                       (platform, fetch_date, sku, score, text, author, review_date, category, source)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (platform, fetch_date, sku, text) DO NOTHING""",
                    (r["platform"], r["fetch_date"], r["sku"], r["score"], r["text"],
                     r["author"], r["review_date"], r["category"], r["source"]),
                )
        conn.commit()
        total += len(rows)
        log(f"  ✓ {sku} 新入库差评 {len(rows)} 条")
    log(f"=== [{args.category}] 完成: 差评新入库 {total} 条 ===")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
