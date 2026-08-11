# OZON 商品上架流程（Step 3）

## ⚠️ 先查 MCP，再调 API（硬规则）

**任何 Ozon API 调用之前，必须先过 ozon-mcp 确认正确格式。**

| 步骤 | 操作 |
|---|---|
| 1 | `ozon_describe_method("ProductAPI_ImportProductsV3")` → 拿 exact JSON Schema |
| 2 | 按 Schema 组装 request body，特别是 `attributes` 字段格式确认 |
| 3 | 用 `ozon_call_method` 代替 raw curl/Python（自带 auth/校验/限频/重试）|
| 4 | 提交后必须调 `v4/product/info/attributes` verify 实际落盘结果 |

**为什么：**
- 凭记忆手撸属性格式已踩坑 3 次（2026-07-24 的 I88 上架）
- MCP 的 swagger 是真理来源，手写的都是野路子
- v3/product/import 静默丢弃属性不报错，不 verify 就不知道结果

---

## 概述

将用户数据 + Step1 关键词 + Step2 图片组装为 Ozon 商品，调 API 上架。
上架时**一次性将属性和简介尽量填满**，减少后续补刀。

**输入：**
- 用户数据汇总表（品名/price/类目ID/重量尺寸/规格参数）
- Step1 Excel（关键词总表 → 标题优化 + #Хештеги + Аннотация）
- Step2 COS 图片路径（8张图）

**数据获取优先级：** `用户数据 > Step1 Excel > 爬竞品`
- 用户提供的 → 优先用
- Step1 有的（关键词/售价/品牌等）→ 直接捞
- 都没有的规格参数 → 去 Ozon 竞品详情页扒

**输出：** Product ID

---

## 前置条件

| 项目 | 说明 |
|---|---|
| Ozon Seller API | Client-Id + Api-Key |
| Base URL | `https://api-seller.ozon.ru` |
| 店铺货币 | CNY |
| VAT | 0% |
| Step1 Excel | `{WORKSPACE}\<日期>_<关键词>_products.xlsx` |
| Step2 COS | `products/<SKU>/<SKU>_01~08.png` |

---

## 步骤 3.1 — 数据校验 & 映射

### 校验

| 字段 | 校验规则 | 不通过处理 |
|---|---|---|
| 品名 | 非空，≤500字符 | 报错要求补充 |
| description_category_id | 调 Ozon 类目树确认存在 | 不存在则报错 |
| type_id | 确认与类目匹配 | 不匹配则查类目树校正 |
| price | 数字 > 0 | 无效报错 |
| weight / width / height / depth | 数字 > 0 | 报错 |

### 映射

```python
old_price = round(price * 1.3, 2)
currency_code = "CNY"
vat = "0"
```

---

## 步骤 3.2 — 标题优化

### 数据来源

| 来源 | 用途 |
|---|---|
| Step1 竞品总表 → 品名 | 原标题参考 |
| Step1 关键词总表 → 高曝光词（排前面） | 核心搜索词 |
| Step1 关键词总表 → 高增长词（补充） | 长尾流量 |
| Step1 主题标签表 → 品类词 | 补充标签 |

### 规则

```
格式：<核心类型> <核心卖词1> <核心卖词2> <核心卖词3>
限制：≤500 字符，俄语
```

---

## 步骤 3.3 — 组装请求体（重点：属性一次性填满）

### Body 基础字段

```json
{
  "items": [{
    "offer_id": "",                     // 不传自动生成
    "name": "优化后的标题",
    "description_category_id": 17039623,
    "type_id": 970684979,
    "price": "250.00",
    "old_price": "325.00",
    "currency_code": "CNY",
    "vat": "0",
    "weight": 1500,
    "weight_unit": "g",
    "width": 280,
    "height": 220,
    "depth": 120,
    "dimension_unit": "mm",
    "images": ["8张COS图片URL"]
  }]
}
```

### Attributes — 必填基础项

| ID | 名称 | 填法 | 来源 |
|---|---|---|---|
| 8229 | Тип | 字典ID | 按type_id匹配 |
| 85 | Бренд | `"No Brand"` | 固定 |
| 4389 | Страна | `"Китай"` | 固定 |
| 5283 | Питание | 字典ID | 按品类默认 |
| 4854 | Пылесборник | 字典ID | 按品类默认 |
| **23171** | **#Хештеги** | text | **Step1关键词Top词拼接** |
| **4191** | **Аннотация** | text | **Step1数据拼接描述** |
| 9048 | Название модели | 留空 | — |

### #Хештеги 拼接规则

从 Step1 关键词总表取 Top 高曝光词，空格分隔加 #：
```
#пылесос #матрас #клещи #беспроводной #УФ #HEPA #дезинфекция #аллергия #уборка #мебель
```

### Аннотация 拼接规则

从 Step1 数据拼接：
```
<核心卖点><规格参数><配件清单><使用场景>
目标：≥500字符（Content Rating +50分）
```

### Attributes — 规格参数（尽力填满，目标33+个）

有数据的直接用，没数据的**从竞品详情页扒**。

| ID | 名称 | 类型 | 建议值（除螨仪示例） |
|---|---|---|---|
| 4852 | Мощность всасывания, Вт | Decimal | `"120"` |
| 21363 | Сила всасывания, Па | Integer | `"8000"` |
| 4864 | Макс. уровень шума, дБ | Decimal | `"65"` |
| 4866 | Время работы, мин | Decimal | `"30"` |
| 9650 | Время зарядки, ч | Decimal | `"4"` |
| 4855 | Объем пылесборника, л | Decimal | `"0.5"` |
| 10096 | Цвет товара | 字典ID或text | `"Белый"` |
| 4860 | Вид насадки | 字典ID或text | `"Щелевая насадка"` |
| 4859 | Количество насадок | text | `"3"` |
| 4895 | Количество режимов | text | `"2"` |
| 4853 | Вид фильтра | 字典ID或text | `"HEPA"` |
| 9226 | Тип уборки | 字典ID | `"Сухая"` |
| 10403 | Работа от аккумулятора | text | `"Да"` |
| 4383 | Вес товара, г | Decimal | `"800"` |
| 4497 | Вес с упаковкой, г | Decimal | `"1500"` |
| 4382 | Размеры, мм | text | `"250x150x100"` |
| 4384 | Комплектация | text | 配件清单 |
| 4867 | Особенности | text | 卖点描述 |
| 10400 | Гарантия | text | `"1 год"` |
| 5391 | Длина шнура, м | Decimal | `"0"`（无线） |
| 11650 | Количество заводских упаковок | text | `"1"` |

### 字典ID 查询

通过接口获取：
```
POST /v1/description-category/attribute/values/search
Body: { description_category_id, type_id, attribute_id, value: "<搜索词>" }
```

---

## 步骤 3.4 — 调用上架接口

**POST** `https://api-seller.ozon.ru/v3/product/import`

**Headers:**
```
Client-Id: <your_client_id>
Api-Key: <your_api_key>
Content-Type: application/json
```

---

## 步骤 3.5 — 验证结果

轮询 **POST** `/v1/product/import/info`

```
task_id → status=imported → 检查errors
  ├─ 0 error → ✅ 成功
  ├─ 只有warning → ⚠️ 记录，不阻塞
  └─ 有error → 修复后重试
```

成功后记录 Product ID，调评分接口确认 Content Rating：
```
POST /v1/product/rating-by-sku
→ 目标：≥80分（属性填满33+个 + 简介≥500字 + 8张图）
```

---

## 注意事项

1. 字典型 attribute 必须用 `dictionary_value_id`，不能只用 `value`
2. 所有数值字段必须传字符串（如 `"1"` 而非 `1`）
3. type_id 和 description_category_id 必须匹配同一品类树
4. 图片 URL 必须可公开访问（公有读 COS）
5. #Хештеги 和 Аннотация 直接决定搜索评分，优先填
6. 规格参数优先用用户提供的数据，没有就抄竞品
7. 目标：上架时 attributes 填到 33+ 个，一次性拉高 Content Rating
