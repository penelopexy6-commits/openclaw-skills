# OZON + SeerFar 竞品数据采集流程（Step 1）

## 概述

从运营填写的需求出发，按条件搜索 OZON 筛选竞品 SKU，调用 SeerFar API 逐条写入 Excel 模板（4 个 Sheet），按提交人导出到独立文件夹。

**核心原则：**
- 逐条落盘，不攒批 → 拿一条写一条，每一步即时保存
- 关键词反查等通知 → 不自动跑，避免浪费积分
- 限频 5秒/次 → 实测可稳定运行，偶见429（脚本自动重试）
- 按提交人分文件 → 每人一个独立 `竞品数据.xlsx`，放 `{OUT_DIR}/{提交人A|提交人B|提交人C}`

---

## 前置条件

| 项目 | 说明 |
|---|---|
| SeerFar API Key | `Authorization: Bearer <platform_api_key>` |
| Base URL | `http://api.seerfar.cn` |
| 限频 | 5秒/次（实测OK，文档3秒） |
| 积分查询 | `GET /open-api/quota`（0积分） |
| 脚本路径 | `{WORKSPACE}\step12_product_detail.py` |
| 日志路径 | `{WORKSPACE}\step12_progress.log` |

---

## 输入模板 — `{WORKSPACE}\Step1.xlsx`

### Sheet 1「运营需求」— 运营填写（11列）

| 列 | 字段 | 说明 |
|---|---|---|
| A | 提交人 | 用于按人分文件 |
| B | 中文品名 | |
| C | 俄文品名 | 空则自译补充 |
| D | 产品图 | |
| E | OZON类目（二级） | ⚠️ 用于分文件匹配，必填 |
| F | OZON类目（三级） | |
| G | 产品定位（预估价位区间 ₽） | 价位窗口计算基准 |
| H | 平均售价（竞品前台定价 ₽） | |
| I | 规格参数 | |
| J | 竞品链接 | |
| K | 备注 | 含采购成本信息 |

---

## 步骤 1.1 — OZON搜品取SKU

**目标：** 按确认的关键词+价位窗口搜索OZON，取前40个SKU，写入Excel

### 价位窗口算法
```
最低价 = 产品定位 × 0.7（-30%）
最高价 = 产品定位 × 1.3（+30%）
```
⚠️ 注意：对垂类/小品类（如智能手表、脱毛仪），±30%可能过窄导致SKU太少（常见仅8个）。
如遇此类情况，需手动放宽到 ±50% 或取消价格过滤重新搜。

### 搜索流程

1. **启动浏览器**
   ```bash
   playwright-cli open https://www.ozon.ru --headed --persistent
   ```
   ⚠️ `--headed` 显示GUI窗口，`--persistent` 持久化配置防OZON反爬

2. **带价格过滤搜索**
   - URL格式：`https://www.ozon.ru/search/?text={俄文关键词}&price={最低};{最高}`
   - 使用URL编码的俄文关键词

3. **滚动加载 + 提取SKU（一步完成）**
   ```javascript
   window.scrollTo(0, document.body.scrollHeight);
   // 提取所有产品链接中的SKU
   const s = new Set();
   document.querySelectorAll('a').forEach(a => {
     const h = a.href;
     if (!h.includes('/product/')) return;
     const idx = h.lastIndexOf('-');
     const end = h.indexOf('/', idx);
     if (end > 0) {
       const sku = h.substring(idx + 1, end);
       if (/^[0-9]+$/.test(sku)) s.add(sku);
     }
   });
   Array.from(s).slice(0, 40).join(',');
   ```

4. **写入Excel** — 爬到一条写一条，品类头行（品类名+价位区间）加粗，下方逐行写SKU

### 输出

写入Sheet 2「SKU」，格式：
```
| 品类 | SKU |
|---|---|
| Погружной блендер（3150-5850₽） | (空) |
| (空) | 4997390917 |
| (空) | 4773887762 |
| ... | ... |
```

---

## 步骤 1.2 — 商品详情API → 逐条写入Sheet 3

**目标：** 对Sheet 2的SKU逐个调API，每返回一条即时写入Sheet 3「shuju」

### 执行

```bash
python3 {WORKSPACE}\step12_product_detail.py <目标Excel路径>
```

对每个提交人依次执行：
```bash
python3 scripts/step12_product_detail.py "{OUT_DIR}/提交人A/竞品数据.xlsx"
python3 scripts/step12_product_detail.py "{OUT_DIR}/提交人B/竞品数据.xlsx"
python3 {WORKSPACE}\step12_product_detail.py "{OUT_DIR}\{店铺名}\竞品数据.xlsx"
```

### 接口

```
POST /open-api/product/detail/search/ozon
费用: 3 积分/次
限频: 5秒/次
```

### 请求体
```json
{ "sku": "<SKU>", "dateRange": "past_30_days" }
```

### 写入逻辑

- **每返回1条立即写** → 追加一行到Sheet 3，`wb.save()`
- 不攒批、不等全部完成
- 已存在的SKU自动跳过（避免重复写）
- 中途崩了也只丢当前那一条

### 字段映射（Sheet 3「shuju」33列）

| # | Excel 列名 | API 来源 | 说明 |
|---|---|---|---|
| 1 | SKU | `data.product.sku` | |
| 2 | 平台 | 固定 `OZON` | |
| 3 | 链接 | `data.product.productUrl` | |
| 4 | 标题 | `data.product.title` | |
| 5 | 类目 | `data.product.categoryInfo.cnTitlePath` | |
| 6 | 链接（重复） | `data.product.productUrl` | 模板冗余列 |
| 7 | 图片URL | `data.product.imageUrls[0]` | |
| 8 | 品牌名称 | `data.product.brandName` | |
| 9 | 类目（重复） | `data.product.categoryInfo.cnTitlePath` | |
| 10 | 售价(₽) | `data.product.price` | |
| 11 | 折扣率 | `data.product.discount` | |
| 12 | 促销收入占比 | `data.product.promoRevenueShare` | |
| 13 | 毛利率 | `data.product.grossMargin` | 可能null |
| 14 | 近30天总销量 | `data.totalSales` | |
| 15 | 日均销售额 | `data.totalRevenue / 30` | 计算值 |
| 16 | 日均销量 | `data.dailySales` | |
| 17 | 广告费用份额(%) | `data.product.drr` | |
| 18 | 近30天总访问量 | `data.product.sessionCount` | |
| 19 | 近30天搜索流量 | `data.product.sessionCountSearch` | |
| 20 | 搜索→加购转化率(%) | `data.product.convToCartSearch` | |
| 21 | 详情→加购转化率(%) | `data.product.convToCartPdp` | |
| 22 | 浏览→下单转化率(%) | `data.product.convViewToOrder` | |
| 23 | 下单转化率(%) | `data.product.orderConversionRate` | |
| 24 | 退货取消率(%) | `data.product.returnCancellationRate` | |
| 25 | 广告 | `data.product.drr` | |
| 26 | 上架时间 | `data.product.upTime` | ms→日期(UTC+3) |
| 27 | 商品图片链接 | `data.product.imageUrls[0]` | |
| 28 | 卖家类型 | `data.product.sellerType` | 0本土/1跨境 |
| 29 | 仓储模式 | `data.product.fulfillment[0]` | |
| 30 | 重量(g) | `data.product.weight` | |
| 31 | 体积(L) | `data.product.volume` | |
| 32 | 包装尺寸(mm) | `data.product.dimension` | |
| 33 | 是否允许跨境 | `data.product.categoryInfo.crossBorderSellable` | |

### 进度监控

- 实时日志：`{WORKSPACE}\step12_progress.log`
- 每个SKU输出一行，形如 `[1/322] SKU 5104017694... OK — price=1340.0`
- 结束时输出汇总：成功数/失败数/积分消耗

---

## 步骤 1.3 — 关键词反查 ⚠️ 等通知再跑

**不自动执行：**
1. 先等运营确认竞品数据，判断该品类有可行性
2. 运营通知「可以查关键词了」
3. 再调API

### 接口

```
POST /open-api/keyword/backSearch/ozon
费用: 15 积分/次（最多20个SKU/次）
限频: 5秒/次
```

### 请求体
```json
{
  "skuIds": [SKU1, SKU2, ...],
  "hasVariant": 0,
  "page": {
    "pageNumber": 1,
    "pageSize": 100,
    "orders": [{ "field": "exposure", "direction": "DESC" }]
  }
}
```

⚠️ `pageSize` 最大100，超过会400错误

### 字段映射（Sheet 4「关键词总表」22列）

| # | Excel 列名 | API 来源 | 说明 |
|---|---|---|---|
| 1 | SKU | 所属SKU | |
| 2 | 关键词(俄文) | `data.records[].query` | |
| 3 | 关键词(中文) | `data.records[].queryCn` | |
| 4 | 出现次数 | 统计 | |
| 5 | 月搜热度 | `data.records[].searchVolume` | |
| 6 | 月搜增长(%) | `data.records[].count30GrowthRate` | |
| 7 | 平均售价(руб) | `data.records[].avgPrice` | |
| 8 | 商品总数 | `data.records[].productCount` | |
| 9 | 竞品数 | `data.records[].competingProducts` | |
| 10 | 广告竞对数 | `data.records[].adRivalCount` | |
| 11 | 加购转化率(%) | `data.records[].ca` | |
| 12 | 加购数 | `data.records[].uniqQueriesWCa` | |
| 13 | 转化集中度(%) | `data.records[].conversionSharing` | 越高头部垄断越强 |
| 14 | 市场空间 | `data.records[].marketSpace` | 越小越饱和 |
| 15 | 退货取消率(%) | `data.records[].returnCancellationRate` | |
| 16 | 曝光占比(%) | `data.records[].viewSharing` | |
| 17 | 自然排名 | `data.records[].dimension.naturalRank` | |
| 18 | 广告排名 | `data.records[].dimension.adRank` | |
| 19 | 广告竞对数 | `data.records[].dimension.adRivalCount` | |
| 20 | 曝光贡献度(%) | `data.records[].dimension.exposure` | |
| 21 | 转化贡献度(%) | `data.records[].dimension.conversion` | |
| 22 | Top10商品标题 | `data.records[].products[0:10].title` | 拼接 |

---

## 步骤 1.4 — 按人分文件 & 导出

所有数据采集完后，按提交人拆分为独立文件。

### 分文件逻辑

**关键规则：用OZON类目路径匹配，不用关键词匹配！**
关键词匹配会误判（如"Отпариватель"同时匹配提交人A的挂烫机和提交人B的蒸汽熨斗）。

**类目路径示例：**
- 提交人A：家用电器 / 文具 / 运动护具
- 提交人B：电子产品 / 美容健康 / 旅游配件
- {店铺名}：宠物用品 / 家居 / 工具 / 空调设备

### 输出目录结构

```
{OUT_DIR}\
├── 提交人A\
│   └── 竞品数据.xlsx  ← 4个Sheet：yunying / SKU / shuju / guanjainci
├── 提交人B\
│   └── 竞品数据.xlsx
└── hu\
    └── 竞品数据.xlsx
```

### 脚本

```bash
python3 scripts/split_exports.py(已归档)
```

---

## 积分成本参考（按30品类×40SKU估算）

| 步骤 | 积分/次 | 次数 | 小计 | 实测 |
|---|---|---|---|---|
| 1.2 商品详情 | 3 | 500~550 | 1,500~1,650 | 实际2,979 |
| 1.3 关键词反查 | 15 | 1~2/品类 | 450~900 | 待跑 |
| **合计** | | | **~2,500+** | **2,979 已用** |

注：实测成功率~82%，失败不扣分但SKU重试消耗少量额外积分。

---

## 📌 踩坑记录 & 优化空间

### 已知问题

#### 1. 分文件时品类匹配方式
- ❌ **不要用俄文关键词匹配** → "Отпариватель"同时匹配挂烫机和蒸汽熨斗
- ✅ **用OZON类目路径匹配** → 无重叠

#### 2. 价位窗口过窄
- 大品类（家电/厨电）±30% 正常 → 可捞30-40 SKU
- 小品类（智能手表/脱毛仪/工具）±30% 过窄 → 只捞到8个
- **解法：** 运营填的「产品定位」如果是精确零售价（4323₽），窗口就会很窄。如遇此类，放宽到±50%或直接不限制价格搜

#### 3. Unicode特殊字符写Excel报错
- 个别商品标题含 `\u200b`（零宽空格）等特殊字符
- openpyxl写xlsx时遇到会报 `'gbk' codec can't encode character`
- **影响：** 跳过该条，不影响整体运行
- **待修复：** 脚本写入前过滤或替换特殊字符

#### 4. 脚本重启导致数据丢失
- **历史问题已修复：** 改为逐条落盘（每写一条 `wb.save()`），崩了只丢当前一条
- 但脚本开头会清空shuju表再写，如果没来得及保存就被杀，数据会丢
- **建议：** 稳定运行期间不要杀进程，如需中断等当前SKU处理完再 kill

#### 5. SeerFar 数据覆盖率
- 实测产品数据覆盖率约 80-93%
- 大品牌/知名产品覆盖率更高
- 无品牌/新上架产品经常查不到
- 这不是问题，是正常现象

### P0 待优化
- [ ] 脚本增加特殊字符过滤（`re.sub(r'[\u0000-\u001f\u200b\u200e\u200f]', '', text)`）
- [ ] 小品类价位窗口自动放宽逻辑
- [ ] 分文件脚本的类目匹配改用类目路径而非关键词
- [ ] 批量运行3个文件的自动化脚本（避免手动敲3次）

---

## 文件清单

| 文件 | 用途 |
|---|---|
| `{WORKSPACE}\Step1.xlsx` | 运营需求原始模板 |
| `{WORKSPACE}\step12_product_detail.py` | Step 1.2 API采集脚本 |
| `{WORKSPACE}\split_exports.py` | 按人分文件脚本 |
| `{WORKSPACE}\append_skus.py` | SKU追加写入（单品类用） |
| `{WORKSPACE}\step12_progress.log` | 运行日志 |
| `{WORKSPACE}\skus_accumulate.json` | SKU采集临时缓存 |
| `{OUT_DIR}/提交人A/竞品数据.xlsx` | 提交人A的竞品数据 |
| `{OUT_DIR}/提交人B/竞品数据.xlsx` | 提交人B的竞品数据 |
| `{OUT_DIR}\{店铺名}\竞品数据.xlsx` | {店铺名}的竞品数据 |
