---
name: "ozon-daily-monitor"
description: "Ozon 店铺每日监控四合一（销量/曝光/营销价/商品洞察）→ ozon_data 固定表增量 upsert"
---

# Skill: ozon-daily-monitor

Ozon 店铺每日监控四合一：**销量 + 曝光 + 营销价 + 商品洞察**，数据增量落库 `ozon_data`（PostgreSQL 16 + pgvector）。

## 适用场景

- 每天固定时间自动拉取店铺运营数据
- 新店铺接入监控（改凭证即可）
- 分析排名/价格/销量的历史趋势

## 核心原则（老大定版）

1. **表结构只初始化一次**（`CREATE TABLE IF NOT EXISTS`），日常运行只做 **upsert 增量写**（`ON CONFLICT ... DO UPDATE`），绝不重建表
2. 首次跑通的数据表后续直接复用；新表按需补建
3. 代理不通自动跳过（cron 脚本先检查 SOCKS 代理（默认 10808）），次日补拉

## 表结构（8 张，ozon_data 库）

| 表 | 主键 (UNIQUE) | 内容 |
|---|---|---|
| `daily_sales` | (platform, stat_date, sku) | 每日销量/营收（analytics/data） |
| `exposure_daily` | (platform, fetch_date, sku, query) | 查询词曝光（搜索/曝光/排名/转化） |
| `price_snapshots` | (platform, fetch_date, product_id) | 营销价快照（v5 prices） |
| `product_state_snapshots` | (platform, fetch_date, product_id) | 可见性 + 描述全文 |
| `search_queries_top` | (platform, fetch_date, query) | 热词榜（需 Premium Pro） |
| `search_queries_text` | (platform, fetch_date, search_text, query) | 按文本搜词（需 Premium Pro） |
| `competitor_prices` | (platform, fetch_date, product_id) | 定价策略竞品价（需先加策略） |
| `competitor_prices_front` | (platform, fetch_date, query, sku) | 前台竞品价（ozon_search） |

DDL 见 `scripts/` 各脚本注释或 Obsidian `08-数据库表结构.md`（全字段中文注释）。

## 脚本（workspace/scripts/）

| 脚本 | 接口 | 说明 |
|---|---|---|
| `ozon_daily_sales.py` | /v1/analytics/data | 销量（--days N / --from --to） |
| `ozon_exposure.py` | /v1/analytics/product-queries/details | 曝光（7 天滚动，400 自动回退窗口） |
| `ozon_price.py` | /v5/product/info/prices | 营销价（--date 补拉） |
| `ozon_insight.py` | visibility/description/search-queries/pricing | 商品洞察（--module 单独跑） |

统一特征：`load_creds()` 从 `.env.secrets` 读 `SHOP_OZON_CLIENT_ID/API_KEY`；SOCKS 代理 10808（PySocks 模块级设置）；psycopg2 upsert。

## cron（每日 09:05）

```
5 9 * * * $WORKSPACE/scripts/ozon_daily_monitor.sh
```

`ozon_daily_monitor.sh` 逻辑：检查 SOCKS 代理（默认 10808） → 不通跳过 → 依次跑 sales(2天) → exposure(7天) → price(当天) → insight(全模块) → 日志 `logs/ozon_daily_monitor.log`。

## 踩坑速查（重要）

1. **429 限频**：长退避重试（10/20/30s），SKU 间隔 ≥6s
2. **400 = 参数问题不重试**：exposure 窗口含未计算日期（date_to=today-1）→ `There is no data for the specified period`；默认窗口 **today-8 ~ today-2** + 400 自动回退
3. **403 = 权限不足不重试**：search-queries 需 Premium Pro（当前店铺 PREMIUM，API 实测为准）
4. **空字符串入库**：接口返回 `''` 插 timestamptz 报错 → 统一 `or None`
5. **SKU 映射**：v3/product/info/list 返回 map 键是 product_id，落库按 sku 反查 offer_id
6. **TUN 模式**：跑 API 脚本要开 V2ray；浏览器访问前台要关（互斥，见 ozon-competitor-price-research）

## 使用步骤

```bash
# 1. 确保 V2ray 开着（SOCKS5 代理，默认 127.0.0.1:10808，可配置）
# 2. 首次：建表（各脚本首次运行自动 CREATE IF NOT EXISTS）
# 3. 手动跑
cd $WORKSPACE
.venv/bin/python scripts/ozon_daily_sales.py --days 2
.venv/bin/python scripts/ozon_exposure.py --days 7
.venv/bin/python scripts/ozon_price.py --date 2026-08-06   # 补拉指定日
.venv/bin/python scripts/ozon_insight.py                    # 全模块
# 4. cron 每日 09:05 自动跑；补拉用 --date/--days 参数
```

## 验证

- 落库行数：`SELECT count(*) FROM daily_sales;` 等
- 最新日期：`SELECT max(stat_date) FROM daily_sales;` / `max(fetch_date)` 各表
- 汇总看数：三表联查（sales + exposure + price）出运营日报
