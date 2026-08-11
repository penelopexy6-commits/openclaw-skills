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
| `db_config.py` | 统一数据库配置（引用，不打包） |

## 关键参数（V2 定版）

- HDBSCAN：`min_cluster_size=5`，欧氏距离（向量 L2 归一化后 = 余弦）
- 质心匹配阈值：`0.75`（唯一可靠继承闸门，0.73 就跌破 80% 一致率）
- 短文本：全量参与聚类，靠质心匹配继承
- 代表数：每簇 3 条（5 条反而更差——投票被噪声污染）

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
