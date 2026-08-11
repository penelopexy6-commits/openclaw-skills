---
name: "ozon-competitor-price-research"
description: "Ozon 前台竞品价格调查：Edge CDP 直连（关 V2ray）→ ozon_search → competitor_prices_front 增量落库 → 价格带分析"
---

# Skill: ozon-competitor-price-research

Ozon **前台竞品价格调查**：用真实浏览器（Edge CDP）搜目标词，抓竞品价格落库 `competitor_prices_front` 表，输出价格带分析。

## 适用场景

- 某商品定价是否合理（vs 前台竞品）
- 类目价格带摸底（普通款 vs 功能款）
- 改价/活动前竞品侦查

## ⚠️ 前置：网络互斥（最重要）

**浏览器访问 Ozon 必须关 V2ray**（TUN 模式全局接管 → Edge 出口变代理 IP 203.10.99.34 → Ozon WAF「Похоже, нет соединения」）。
- API 脚本（api-seller.ozon.ru）**要**代理（SOCKS5 代理，默认 127.0.0.1:10808，可配置）
- 前台（www.ozon.ru）**要**直连（中国 IP 可过）——两者互斥，切换时告知用户

## 步骤

### 1. 确认/启动 Edge CDP（9223）

```bash
# 检查
curl -s http://127.0.0.1:9223/json/version | grep Browser
# 清理残留（有进程但端口不通时）
pkill -f "remote-debugging-port=9223"; sleep 3
# 启动（Windows Edge，WSL2 interop；--no-proxy-server 对 TUN 无效，关 V2ray 才是正解）
setsid "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --remote-debugging-port=9223 --user-data-dir="C:\\edge-cdp-profile" \
  --no-first-run --no-default-browser-check about:blank >/dev/null 2>&1 < /dev/null & disown
sleep 10
```

### 2. 预热 + 验证 Ozon 可达

```bash
cd $WORKSPACE
playwright-cli attach --cdp http://localhost:9223
playwright-cli goto "https://www.ozon.ru/search/?text=<关键词URL编码>"
playwright-cli eval "document.title"
# 标题含 "купить на OZON" = 成功；"Похоже, нет соединения" = 被 WAF 拦（检查 V2ray 关了没）
```

### 3. 结构化搜索（ozon-front MCP，tier-2 CDP）

调用 `ozon-front__ozon_search`（query=俄文搜索词）→ 返回 items[]：sku/title/price/price_original/rating/rating_count/stock/url。

多词搜索：目标词 + 功能细分词（例：主词 + «антибликовые»）看价格带差异。

### 4. 落库（增量 upsert，不重建表）

表 `competitor_prices_front`：UNIQUE(platform, fetch_date, query, sku)，DDL：

```sql
CREATE TABLE IF NOT EXISTS competitor_prices_front (
  id BIGSERIAL PRIMARY KEY,
  platform VARCHAR(20) NOT NULL DEFAULT 'ozon',
  fetch_date DATE NOT NULL,
  query VARCHAR(255) NOT NULL,
  sku BIGINT NOT NULL,
  title TEXT, price NUMERIC(12,2), price_original NUMERIC(12,2),
  rating NUMERIC(3,1), rating_count INT, stock VARCHAR(50), url TEXT,
  source VARCHAR(30) DEFAULT 'ozon_search_front',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (platform, fetch_date, query, sku)
);
```

插入用 `INSERT ... ON CONFLICT DO UPDATE`，同日同词同 SKU 覆盖。

### 5. 价格带分析

```sql
-- 某词下竞品价格分布
SELECT query, min(price), percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS 中位,
       max(price), count(*), max(rating_count) AS 最高评论数
FROM competitor_prices_front
WHERE query = '<搜索词>' AND fetch_date = (SELECT max(fetch_date) FROM competitor_prices_front)
GROUP BY query;
-- 对标：同规格功能款（例：标题含 антибликовые 且度数相同）单独挑出
SELECT title, price, rating, rating_count FROM competitor_prices_front
WHERE query LIKE '%антибликовые%' AND title LIKE '%+1,5%' ORDER BY price;
```

## 分析口径（实战结论）

- **普通款 vs 功能款价格带不同**：主词 120~922₽，防蓝光细分 1,267~1,466₽——对标必须同规格
- **营销价对比**：自己商品用 price_snapshots.marketing_price（v5），不是设置价
- 评论数影响转化：0 评论 vs 竞品几百~18万评是硬伤

## 踩坑速查

1. TUN 未关 → WAF 拦截页（带 incident_id）→ 让用户关 V2ray
2. Edge 残留进程：pkill 后 setsid 重启（nohup 会被 exec 杀）
3. ozon-front tier-1 常被 Cloudflare 拦 → 自动切 tier-2 CDP；CDP 不可达会报 transport_down
4. 首次搜索前先 goto 一次 ozon.ru 预热（过 Cloudflare 挑战）

## 输出物

- 竞品价格清单（落库）
- 价格带结论（普通带/功能带/自己定位）
- 定价建议（同规格对标 ±）
