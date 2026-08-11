# openclaw-skills

OpenClaw Agent 自建 Skills 集 —— Ozon 电商运营 + AI 工具链。

> 由个人工作流沉淀而来,均为实战验证过的可复用技能。
> 所有密钥/凭证均通过环境变量或 `.env.secrets` 读取,仓库内无任何敏感信息。

## Skills 清单

| Skill | 用途 | 依赖 |
|---|---|---|
| `ozon-daily-monitor` | Ozon 店铺每日监控四合一:销量/曝光/营销价/商品洞察 → PostgreSQL 增量落库 | Ozon Seller API、PostgreSQL、V2ray 代理 |
| `ozon-competitor-price-research` | Ozon 前台竞品价格调查:Edge CDP → ozon_search → 价格带分析 | Edge 浏览器、Ozon 前台 |
| `deepseek-batch-translation` | DeepSeek API 批量中英对照翻译:md 解析/分批/缓存续跑/补翻循环 | DeepSeek API key |
| `ozon-seerfar-data-collection` | Ozon 竞品数据采集(SeerFar API 逐条落盘 Excel, 4 Sheet) | SeerFar API |
| `ozon-step2-image-generation` | 电商主图生成(去文字抠白底 + 8图框架批量生成) | Banana Pro API、腾讯云 COS |
| `ozon-step3-listing` | 商品上架(先查 MCP 再调 API, 属性格式验证) | Ozon Seller API |
| `ozon-step5-operations` | 运营优化(广告投放 Performance API + 竞品监控) | Ozon Performance API |
| `vision-look` | 图片识别/视觉理解:AI 看图(硅基流动 Qwen3-VL),OCR/电商图/评价截图 | SiliconFlow API key |

## 快速开始

每个 Skill 目录下有 `SKILL.md`,含完整用法、参数、踩坑记录。OpenClaw 用户可直接将目录放入 `~/.openclaw/workspace/skills/` 或 OpenClaw 插件目录加载。

### 环境变量约定

- 密钥统一从 `.env.secrets`(workspace 根目录)或环境变量读取
- 示例:`SILICONFLOW_API_KEY`、`DEEPSEEK_API_KEY`、`SHOP_OZON_CLIENT_ID/API_KEY`

### 网络注意(Ozon 相关)

- Ozon Seller API:需走 SOCKS5 代理(默认 127.0.0.1:10808)
- Ozon 前台(浏览器):需直连,与 API 代理互斥(详见各 SKILL.md)

## 数据库

依赖 PostgreSQL 16 + pgvector,表结构见各 Skill 内 DDL(增量 upsert,不重建表)。

## License

MIT
