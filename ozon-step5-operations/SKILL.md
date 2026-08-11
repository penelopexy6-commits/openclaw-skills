# OZON 运营优化流程（Step 5）

## 概述

上架并补库存后的后续运营：广告投放 + 竞品监控分析。

---

## 步骤 5.2 — 广告投放（Ozon Performance API）

### 前置条件

需先获取 Ozon Performance API 凭证：
1. 登录 `https://seller.ozon.ru/app/settings/api-keys`
2. 创建 Performance API 密钥
3. 拿到 Performance Client ID + Performance Client Secret

### 相关接口

| 接口 | 用途 |
|---|---|
| `POST /api/v1/campaigns` | 创建广告活动 |
| `POST /api/v1/campaigns/{id}/products` | 添加商品到活动 |
| `POST /api/v1/campaigns/{id}/budget` | 设置预算 |
| `POST /api/v1/campaigns/{id}/start` | 启动活动 |
| `GET /api/v1/campaigns` | 查看活动列表 |
| `GET /api/v1/statistics/daily` | 查看每日统计数据 |

### 建议策略

1. **新品破零期：** 小预算搜索广告，投 Step1 高增长关键词
2. **稳定期：** 根据出单关键词调整，加量跑赢的词，关掉亏的词
3. **扩展期：** 测试新词，看曝光和转化再决定是否加量

**操作权限：** 需要你手动登录 Ozon 后台创建活动，或者提供 Performance API 凭证后我来调接口。

---

## 步骤 5.3 — 监控分析

### 功能

自动跟踪自家商品和竞品的状态变化，定期出对比报告。

### 前置条件

| 项目 | 说明 |
|---|---|
| SeerFar API Key | ✅ 已有 |
| 监控的店铺列表 | ⏳ 你后续提供 |
| 监控的商品列表 | 上架后的 Product ID 列表 |

### 监控流程

```
周期：每周一次 或 按需手动触发

1. 自家商品状态
   ├─ POST /v3/product/info/list → 查价格/库存/状态
   └─ POST /v1/product/rating-by-sku → Content Rating

2. 竞品动态
   ├─ SeerFar POST /open-api/product/detail/search/ozon
   └─ 对比上周：价格变化 / 库存变化 / 新品上架

3. 关键词排名
   ├─ SeerFar POST /open-api/keyword/backSearch/ozon
   └─ 看核心词自然排名升了还是掉了

4. 输出报告
   格式：Excel 或 文字摘要
   内容：哪些品要调价 / 哪些词排名掉了 / 竞品什么新动作
```

### 输出示例

```
📊 周报 — 2026-07-17 ~ 2026-07-24

自家商品：
  SKU xxxx — 评分80→82 ↑，排名从第5→第3 ↑
  SKU xxxx — 价格从250降为220 ↓

竞品动态：
  SKU xxxx — 新上架（同品类，价格低10% ⚠️）
  SKU xxxx — 库存从100降到0（断货了 ✅）

关键词变化：
  "пылесос для матраса" — 你从第4→第2 ↑
  "пылесос от клещей" — 你从第3→第7 ↓ （建议加广告）
```

---

## 注意事项

1. 广告接口需 Performance API 凭证（与 Seller API 不同）
2. SeerFar 监控建议每周一次，避免积分消耗过快
3. 不同店铺的监控需要分别配置
4. 报告格式可以根据需要调整（表格 / 文字 / Excel）
