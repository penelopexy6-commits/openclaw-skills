---
name: "ozon-consumer-persona"
description: "Ozon 消费者画像分析：评论采集 → LLM 语义打标 → Persona 聚类 → Obsidian/Dify 归档（3 种模式：逐条/聚类/LangGraph 图引擎）"
---

# Skill: ozon-consumer-persona

Ozon 竞品评论消费者画像全流程：**采集评论 → 清洗 → LLM 语义分析 → SQL 量化 → Persona 聚类 → 报告归档**。

## 适用场景

- 新品/新店上线前，摸清竞品消费者是谁、为什么买、怕什么
- 已有品类迭代：换关键词/主图/广告语时，用 Persona 指导
- 数据基础：评论 ≥500 条效果最佳（SOP V1.0 要求）

## 三种运行模式（按成本/能力选）

| 模式 | 脚本 | 成本 | 能力 |
|---|---|---|---|
| V1 逐条 | `persona_pipeline.py` | 高（每条过 LLM） | 全自动，报告直接可用 |
| V2 聚类 | `cluster_pipeline_v2.py` | 中（-54%） | 先聚类后打标，一致率 81.8% |
| **V3 图引擎（推荐）** | `pipeline_graph.py` | 中 | 断点续跑 + 人工审核 + Persona |

### V3 图引擎核心能力（LangGraph）

- **断点续跑**：SqliteSaver checkpoint，崩溃/重启后 `--resume` 从断点继续，已完成节点不重跑
- **人工审核**：interrupt() 暂停，低置信度簇（痛点标签不纯 <60%）→ 待审清单 → 人工确认后继续
- 状态图：load → embed → cluster → label → review → aggregate → report

### V4 模式开关（品类自适应，2026-08-11 新增）

| 参数 | 用途 | 适用品类 |
|---|---|---|
| `--no-cluster` | 跳过聚类，全量 LLM 打标 | **语义密集品类**（智能手表等，评论话术高度相似 HDBSCAN 分不开） |
| `--min-cluster-size N` | 调 HDBSCAN 最小簇大小 | 默认 5；簇过大可调小 |

**⚠️ 重要教训（智能手表案例）**：语义密集品类（屏幕坏/续航差/断连这类高度相似话术）→ HDBSCAN 只出 2 个超大簇（~900 条/簇）→ 每簇 3 代表投票失真 → 整簇误标同一标签（假象 95% 单一痛点）。**判断方法**：看 `[cluster] N 簇` 日志，若簇数 <5 且单簇占比 >80% → 用 `--no-cluster` 重跑。

## 流程（V1 全自动）

```
1. 采集评论（差评 score_asc + 好评 score_desc，翻页 paging.nextButton）
2. 规则清洗（物流评论过滤：доставка/курьер/упаковка...）
3. LLM 批量语义分析（50条/批 × 3 并发，字段：pain_point/emotion/body_feature/usage_scene/purchase_reason）
4. SQL 量化聚合（痛点排名/购买动机/场景分布/身材分布）
5. Persona 规则聚类（P1 丰满度假 / P2 泳池常客 / P3 大胸刚需 / P4 代买送礼）
6. 报告归档（Obsidian 26-<品类>消费人群画像.md + Dify ②库 + /tmp 临时）
```

## 脚本（workspace/scripts/）

| 脚本 | 说明 |
|---|---|
| `persona_pipeline.py` | V1 全流程（采集依赖 MCP venv：ru-marketplace-mcp 的 ozon-connector） |
| `cluster_pipeline_v2.py` | V2 聚类（bge-m3 向量化 → HDBSCAN → 每簇 3 代表打标 → 继承） |
| `pipeline_graph.py` | V3 LangGraph 图引擎（断点 + 审核，默认参数 mcs=5/thr=0.75） |
| `category_config.py` | **品类配置层（跨品类复用核心）**：每品类定义 LLM 枚举 + Persona 模板 + 落地要点 |
| `fetch_good_reviews.py` | 好评抓取（通用版，4-5 星，购买动机分析用） |
| `fetch_bad_reviews.py` | 差评抓取（通用版，1-3 星，score_asc 翻页） |
| `db_config.py` | 统一数据库配置（引用，不打包） |

## 品类配置（category_config.py）

新增品类只需加一个配置块（prompt_enums + build_personas + landing_points）：

| 品类 | 痛点枚举 | Persona | 落地要点 |
|---|---|---|---|
| 泳衣（默认） | size/chest_support/fading | 丰满度假/泳池常客/大胸/送礼 | 尺码诚实+对照表 |
| 宠物玩具 | durability/squeaker/choking/material | 耐咬刚需/安全敏感/材质挑剔 | 耐咬实测/发声器加固/犬种标注 |
| 眼镜 | lens_quality/degree_wrong/broken/fit | 老花刚需/办公电脑/务实平价 | 度数精准/破损包装/材质如实 |
| 智能手表 | screen/battery/sensor/connect/strap | 健康监测/连接体验/送礼 | 测量校准/续航实测/连接稳定 |

**已验证**：宠物玩具（297 条）不耐咬 63.6% + 3 Persona；眼镜（1,166 条）镜片 26.9%/破损 22.3%/度数 15.5% + 3 Persona；智能手表（968 条，--no-cluster）连接 20%/质量 20%/测量 12.8% + 3 Persona；泳衣回归正常。

## 关键参数（V2 定版）
- HDBSCAN：`min_cluster_size=5`，欧氏距离（向量 L2 归一化后 = 余弦）
- 质心匹配阈值：`0.75`（唯一可靠继承闸门，0.73 就跌破 80% 一致率）
- 短文本：全量参与聚类，靠质心匹配继承
- 代表数：每簇 3 条（5 条反而更差——投票被噪声污染）

## 推理逻辑（为什么这么设计）

一句话：**向量聚类做归纳（哪些评论一类）→ LLM 代表打标做演绎（这类在抱怨什么）→ 阈值控制可信度 → 规则引擎拼 Persona → 品类词典保证语义正确。**

### 1. LLM 打标（V1 逐条）

prompt 结构：品类枚举定义（pain_point/emotion/body_feature/usage_scene/purchase_reason）+ 评论列表 + 要求输出 JSON。

LLM 推理链：**读俄语评论 → 理解抱怨对象 → 映射到枚举 → 输出结构化标签**。

例：`Игрушки хватило на 5-7 минут. Нос был откушен таксой` → 推理：玩具几分钟就坏 → `durability`；提犬种 → `small_dog`；啃咬 → `chew`。

V1 是「每条评论过一遍 LLM」——贵但准。

### 2. 聚类归纳（V2，降本核心）

洞察：60% 评论在说同一件事（尺码/质量/错发），却每条付一次 LLM 钱。改为两步：

```
① bge-m3 把每条评论变成 1024 维向量（语义位置）
   类似话术的评论向量挤在一起
② HDBSCAN 按密度自动分簇（不用预设簇数）→ 20~30 簇，每簇=一类话术
③ 每簇抽离质心最近的 3 条 → LLM 打标 → 投票得簇标签
   （质心=该簇语义最典型的代表）
④ 标签继承：簇内其余几十条直接复用簇标签（0 成本）
```

关键推理：相似语义 → 向量距离近 → 同一簇 → 共享标签。用「代表样本」推断「整簇意图」= 归纳推理。

**阈值 0.75 为什么是生死线**：噪声点（聚类分不进的）先和簇质心算余弦相似度，>0.75 继承标签（0 成本）；<0.75 说明语义太独特，必须 LLM 兜底。实测 0.73 一致率跌破 80%。

### 3. 图引擎保险（V3，LangGraph）

V3 不改变推理，给推理加两道保险：

- **断点续跑**：每节点完成自动 checkpoint，崩溃重启从断点继续，已推理过的绝不重推（省重复花钱）
- **人工审核（human-in-the-loop）**：算每簇标签纯度（簇内最多标签占比），**纯度 <60%** 的簇（一簇里尺码/版型/质量混着）→ 推理不可信 → interrupt() 暂停，样本进待审清单，人工看完 resume。机器拿不准时交给人。

### 4. Persona 规则推理（非 LLM）

打标完成后 Persona 是**数据驱动的规则引擎**：

```
大码提及 >5% 或 尺码痛点 >15% → P1 丰满度假女性
泳池场景 >10% → P2 泳池常客
胸部支撑 >5% → P3 大胸刚需
送礼信号 >2% → P4 代买送礼
```

每类 Persona 的主图/广告/搜索词是预置模板，由痛点百分比填充——报告里每条建议都带真实数据。

### 5. 品类词典（category_config.py）

枚举和 Persona 模板按品类走配置表——推理的「词典」必须匹配品类语义：

```
泳衣词典：size / chest_support / fading
宠物玩具词典：durability 不耐咬 / squeaker 发声器 / choking 易吞
眼镜词典：lens_quality 镜片 / degree_wrong 度数错发 / broken 破损
```

LLM 用对词典推理才有意义（宠物玩具跑出「不耐咬 63.6%」而非泳衣的「尺码 24.6%」）。

## 依赖

- PostgreSQL `ozon_data`（competitor_reviews / review_analysis / embeddings 表）
- 硅基流动 bge-m3（向量化，免费）—— key 从 `{WORKSPACE}/.env.secrets` 的 `SILICONFLOW_API_KEY` 读
- DeepSeek（LLM 打标）—— key 从 OpenClaw `models.json` 读
- LangGraph（V3 模式）：`langgraph` + `langgraph-checkpoint-sqlite`
- 采集（V1）：MCP venv（ozon-connector + mcp_core）

## 踩坑要点（详见 Obsidian 05）

1. 评论翻页必须用 `paging.nextButton`（传错只抓 1 页）
2. LLM 批量 id 回显不可靠 → `[序号]` 格式 + 顺序兜底
3. 差评文本散在 comment/positive/negative 三字段，要合并
4. StateGraph(dict) 返回值整体替换 state → 必须 TypedDict 按字段合并
5. interrupt() 不抛异常，靠 `graph.get_state().next` 非空检测
6. 报告本地不持久化（老大指令）：只归档 Obsidian + Dify，/tmp 临时
7. **语义密集品类聚类失效**（2026-08-11 智能手表）：HDBSCAN 只出 2 超大簇 → 3 代表投票失真（95% 假象）→ `--no-cluster` 全量 LLM 打标；判断：`[cluster] N 簇` 日志中簇数 <5 且单簇 >80%
8. **TypedDict 缺字段被 LangGraph 丢弃**：自定义 state 字段（no_cluster/min_cluster_size）必须加进 PipelineState 声明，否则 invoke 时被过滤
9. **前台价才是真实价**（老坑复现 2026-08-11）：v3/product/info 的 price 是设置价，买家看到的是 v5 prices 的 marketing_seller_price，分析价格一律用 v5
10. ERP 插件改动后必须**重启 Edge CDP** 才生效（搜不到月销字段 = 插件没加载）

## 用法示例

```bash
# V1 全自动（需 MCP venv python）
MCP_VENV/bin/python scripts/persona_pipeline.py --category 泳衣 --skus "1853242673,1419923538" --bad 600 --good 200

# V2 聚类验证
.venv/bin/python scripts/cluster_pipeline_v2.py --category 泳衣

# V3 图引擎（推荐）
.venv/bin/python scripts/persona_pipeline.py --category 泳衣 --graph-auto   # 全自动
.venv/bin/python scripts/persona_pipeline.py --category 泳衣 --graph        # 停人工审核
.venv/bin/python scripts/persona_pipeline.py --category 泳衣 --graph-resume # 审核后续跑
```

## 关联

- SOP《消费者画像分析 SOP V1.0》（老大提供）
- Obsidian：25-胡海店消费人群画像 / 26-泳衣消费人群画像 / 27-画像管线第二版验证
