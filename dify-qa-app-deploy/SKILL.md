---
name: "dify-qa-app-deploy"
description: "Dify 知识库问答应用快速上线框架：任意文档→知识库→问答应用→内网穿透上线，参数化非考勤专用"
---

# Skill: dify-qa-app-deploy

**Dify 知识库问答应用快速上线框架** —— 把任意业务文档（制度/FAQ/操作手册/SOP/产品资料）变成可对外测试的问答机器人，并支持内网穿透公网访问。

适用于：公司临时 demo、内部知识问答、制度咨询机器人、产品 FAQ 助手等。**全程参数化，不绑定任何具体业务**（08-14 考勤问答实战沉淀）。

## 适用场景

- 有一份/多份文档，想快速变成「能问答」的机器人给同事/分部/客户测
- 需要公网链接（异地/跨城市测试）
- 临时 demo，测完可清理，也可长期保留

## 前置条件

- Dify 已本地部署（Docker，`docker ps` 见 dify-nginx-1 等容器，80 端口）
- cpolar 已安装（`~/bin/cpolar`，authtoken 已配置）
- Python venv 可用（`/home/max/.openclaw/workspace/.venv`），脚本：`scripts/dify_login.py` / `scripts/dify_sync_files.py` / `scripts/dify_check_datasets.py`

## 核心原则

1. **纯制度/FAQ 问答 → 不建数据库表**，直接知识库 + 应用。只有「查个人结构化记录」（如某人考勤明细）才需要建表 + 工具接入
2. **上线首选轻量页直连 API**，不用 Dify 官方前端（太重：467KB HTML + 74 JS，1Mbps 穿透下加载几十秒）
3. 改 nginx 配置**只改 template**（`conf.d/default.conf.template`），改 default.conf 重启会被 envsubst 覆盖
4. 所有 Dify 写操作前先 `dify_login.py`（cookie 几小时过期）

## 完整流程（7 步）

### Step 1 — 文档提取（docx/pdf/md 通用）

docx 无需 python-docx，直接解 XML（zipfile）：

```bash
cd /home/max/.openclaw/workspace && .venv/bin/python -c "
import zipfile, re, html
z = zipfile.ZipFile('<文档路径.docx>')
xml = z.read('word/document.xml').decode('utf-8')
xml = xml.replace('</w:p>', '\n')
xml = re.sub(r'</w:tc>', ' | ', xml)
text = re.sub(r'<[^>]+>', '', xml)
text = html.unescape(text)
lines = [l.strip() for l in text.split('\n') if l.strip()]
print('\n'.join(lines))
" > /tmp/<name>.md
```

md 直接复制。产出统一为 Markdown，按章节分节（`# 章节名`），方便检索分段。

### Step 2 — 建知识库

1. `dify_login.py` 刷新登录态
2. 建库 → **PATCH embedding 为 `BAAI/bge-m3`**（默认 bce 禁用，老坑）：

```python
# 建库 POST /console/api/datasets {"name": "<库名>", "indexing_technique": "high_quality", "permission": "only_me"}
# PATCH /console/api/datasets/{id} {"embedding_model": "BAAI/bge-m3"}  ← 必须，否则索引进 completed 但检索异常
```

3. 上传 + 索引：`scripts/dify_sync_files.py --dataset <DATASET_ID> --file /tmp/<name>.md`
4. 轮询 `GET /datasets/{id}/documents` 直到 `indexing_status=completed`

### Step 3 — 建应用 + 绑定知识库

```python
# 建 chat 应用 POST /console/api/apps {"name": "<应用名>", "mode": "chat", "icon": "📋"}
# 绑定：POST /console/api/apps/{app_id}/model-config  ← 只认 POST！GET/PATCH 都 405
```

model-config payload 关键字段（**必须传完整 model_config**，只传 dataset_configs 报 "model is required"）：

```json
{
  "dataset_configs": {
    "retrieval_model": "multiple",
    "datasets": {"datasets": [{"dataset": {"enabled": true, "id": "<DATASET_ID>", "name": "<库名>"}}]},
    "reranking_enable": false,
    "top_k": 4,
    "score_threshold_enabled": false,
    "score_threshold": 0.5
  },
  "pre_prompt": "<见 Step 4 模板>",
  "opening_statement": "<欢迎语>",
  "suggested_questions": ["<常见问题1>", "<常见问题2>", ...]
}
```

### Step 4 — pre_prompt 模板（关键！不设则模型泛泛而谈不检索）

```
你是<角色名>，负责回答<业务范围>相关咨询。

回答规则：
1. 必须优先引用知识库中<文档名>的原文条款来回答
2. 回答要具体明确，直接给出规定的内容/金额/流程/天数，引用对应条款
3. 知识库没有的内容，明确说「<文档名>中未找到相关规定」，不要编造
4. 涉及具体金额、天数、比例时，严格按原文回答
```

**实测教训：** 不设 pre_prompt 时模型回答完全不引用知识库（泛泛而谈法律常识）；设了之后引用条款准确。

### Step 5 — 验证（必须先测再上线）

```bash
# 1. 检索验证（默认参数！别带 score_threshold: 0.0 会返回 0 条）
# POST /console/api/datasets/{id}/hit-testing {"query": "<测试问题>"} → 应有 records 且分数合理

# 2. 问答验证
# POST /console/api/apps/{app_id}/chat-messages {"query": "<测试问题>", "response_mode": "blocking"}
```

每个业务准备 2-3 个代表性场景问题验证回答质量。

### Step 6 — 上线（cpolar 穿透 + 轻量页）

**6.1 生成 API key：** `POST /console/api/apps/{app_id}/api-keys` → 返回 `app-xxx...`

**6.2 轻量页（3.8KB 单文件，绕开重前端）：**
- 模板在 `templates/chat_lite.html`，需替换 3 处：`<API_KEY>`、`<APP_NAME>`、`<WELCOME_MSG>`
- 部署到 `dify/volumes/certbot/www/`（nginx 容器挂载 /var/www/html，root 属主需 sudo 写）

**6.3 nginx 路由（只改 template！）：**
- 编辑 `dify/nginx/conf.d/default.conf.template`，在 server 块内（如 `location /mcp` 后）加：

```nginx
    location = /kq.html {
        root /var/www/html;
        default_type text/html;
        add_header Cache-Control "no-cache";
    }
    location = /kq {
        return 301 /kq.html;
    }
```

- ⚠️ 不要新建独立 conf 文件：两个 server 块都 listen 80 + server_name `_` 时 nginx 只认第一个，新文件不生效
- ⚠️ 不要在容器内手动跑 envsubst（无环境变量会把 `${NGINX_PORT}` 写死导致 emerg），**重启容器最稳**：

```bash
docker restart dify-nginx-1   # entrypoint 会用环境变量重新生成 default.conf
```

**6.4 启动隧道：**

```bash
nohup ~/bin/cpolar http 80 > ~/logs/cpolar.log 2>&1 &
# 日志里找 "Tunnel established at https://xxxxx.rXX.cpolar.top"
```

**6.5 验证：** 公网 curl 轻量页 200 + API 问答一次。

### Step 7 — 清理（可选）

```bash
# 删应用 + 删知识库（先 dify_login.py 刷新）
DELETE /console/api/apps/{app_id}
DELETE /console/api/datasets/{dataset_id}
# 还原 template、删静态文件、重启 nginx
```

## 踩坑清单（08-14 实战，全部实测）

| # | 坑 | 解法 |
|---|---|---|
| 1 | `GET/PATCH /apps/{id}/model-config` 405 | 用 POST |
| 2 | POST model-config 只传 dataset_configs 报 "model is required" | 传完整 model_config |
| 3 | `retrieval_model: "multi_retrieval"` 不检索 | 用 `"multiple"` + reranking/top_k/score_threshold 全套 |
| 4 | 无 pre_prompt → 模型不引用知识库 | 必须设，模板见 Step 4 |
| 5 | 建库默认 embedding bce 禁用 | PATCH `BAAI/bge-m3` 再上传 |
| 6 | hit-testing 带 `score_threshold: 0.0` 返回 0 条 | 用默认参数 |
| 7 | 改 default.conf 重启被覆盖 | 只改 default.conf.template |
| 8 | 新建 server 块不生效（server_name 冲突） | 加进现有 server 块 |
| 9 | 容器内手动 envsubst 写坏配置 | docker restart 重新生成 |
| 10 | webapp 路径 `/a/{token}` 404 | 这版是 `/chat/{access_token}` |
| 11 | cookie 几小时过期 401 | 先跑 dify_login.py |
| 12 | cpolar 3.3.13 下载 404 | 用 `https://www.cpolar.com/static/downloads/releases/3.3.12/cpolar-stable-linux-amd64.zip` |

## 验证标准

- [ ] 知识库索引 completed，hit-testing 命中测试问题
- [ ] 2-3 个场景问题回答引用原文条款准确
- [ ] 轻量页公网 200，加载 < 1s，问答 5-10s 内返回
- [ ] 未收录问题模型明确说「未找到」不编造

## 相关

- 本地 Dify：http://127.0.0.1（admin 登录）
- cpolar 隧道保留中：`https://7ad5528f.r30.cpolar.top`
- 参考：memory/2026-08-14.md（考勤 demo 全流程实录）
