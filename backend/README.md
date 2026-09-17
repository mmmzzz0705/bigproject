# 政明白（GovRAG）—— 后端服务层（FastAPI + AI 应用层）

基于 **FastAPI** 的后端服务层，负责参数校验、跨域处理、会话管理、异常捕获，转发请求到 AI 应用层（RAG），读写 **PostgreSQL**，向前端返回结果；文本块与向量存放于 **Milvus** 向量库。

## 一、目录结构

```
backend/
├─ app/
│  ├─ main.py              # 应用入口：CORS、路由注册、异常捕获、启动初始化
│  ├─ config.py            # 全局配置（环境变量 / .env）
│  ├─ database.py          # 数据库引擎与会话
│  ├─ models.py            # ORM 模型：session / chat_history / doc_meta
│  ├─ schemas.py           # Pydantic 请求响应模型与参数校验
│  ├─ routers/
│  │  ├─ session.py        # POST /api/session/create
│  │  ├─ chat.py           # POST /api/chat（核心）
│  │  ├─ history.py        # GET  /api/chat/history
│  │  └─ corpus.py         # 工作台语料管理：列表 / 上传 / 粘贴 / 删除 / 重新导入
│  ├─ services/
│  │  ├─ rag.py            # RAG 核心链路编排 + 相关性判定
│  │  ├─ corpus.py         # 语料在线编排（落盘 → 入库 → 元数据 → 删除清理）
│  │  ├─ vectorstore.py    # 向量库抽象（内存 / Chroma / Milvus）+ BM25 混合检索
│  │  ├─ milvus_store.py   # Milvus 向量库实现（COSINE + AUTOINDEX）
│  │  ├─ embeddings.py     # Embedding（hash / OpenAI / 通义千问原生多模态）
│  │  ├─ llm.py            # 大模型（extractive / OpenAI / 通义千问）
│  │  ├─ material.py       # 结构化材料清单抽取
│  │  ├─ prompts.py        # Prompt 模板（强约束，抑制幻觉）
│  │  ├─ context.py        # 多轮上下文读取与裁剪
│  │  └─ ingest.py         # 离线文档预处理：加载→清洗→分块→向量化入库
│  └─ utils/text.py        # 文本清洗、章节切分、重叠分块、输入过滤
├─ scripts/
│  ├─ ingest.py                    # 离线预处理命令行脚本（导入 data/docs）
│  ├─ import_existing_vectors.py   # 导入已有 RAG 管道的「片段 + 预计算向量」
│  └─ test_api.py                  # 接口冒烟测试
├─ sql/
│  ├─ schema.sql                   # MySQL 建表脚本
│  └─ schema_postgres.sql          # PostgreSQL 建表脚本（默认）
├─ data/docs/                      # 示例政务文档（6 篇）
└─ requirements.txt
```

## 二、快速启动

```bash
pip install -r requirements.txt
cp .env.example .env        # 可选：不配置也能直接跑（自动降级）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>
- 启动时若向量库为空，自动导入 `data/docs` 下的示例文档（可用 `AUTO_INGEST_ON_STARTUP=false` 关闭）

## 三、接口说明

| 接口 | 方法 | 请求 | 返回 |
| --- | --- | --- | --- |
| `/api/session/create` | POST | — | `{ "session_id": "xxx" }` |
| `/api/chat` | POST | `{ "session_id": "xxx", "question": "..." }` | `{ "answer": "...", "material_list": {...}, "sources": [...] }` |
| `/api/chat/history` | GET | `?session_id=xxx` | `[{ "id", "question", "answer", "create_time" }]` |
| `/api/health` | GET | — | 数据库 / 向量库 / 模型 provider 状态 |

### 3.1 语料管理（工作台）

| 接口 | 方法 | 请求 | 返回 |
| --- | --- | --- | --- |
| `/api/corpus` | GET | — | `{ total, total_chunks, vector_store, docs: [{ doc_id, doc_name, source, chunks, origin, in_index, can_reingest }] }` |
| `/api/corpus/upload` | POST | `multipart: file`（txt/md/pdf/docx，≤10MB） | `{ doc_id, doc_name, chunks }` |
| `/api/corpus/text` | POST | `{ title, content }` | `{ doc_id, doc_name, chunks }` |
| `/api/corpus/{doc_id}` | DELETE | — | `{ removed_chunks, file_removed, recoverable }` |
| `/api/corpus/{doc_id}/reingest` | POST | — | `{ doc_id, doc_name, chunks }` |

两条约定：

- **同名 = 更新**：`doc_id` 由文件名哈希而来，重复上传同一文件名会先清旧片段再写入，不会留下重复副本。
- **内置语料只清向量**：`DOCS_DIR`（容器里是只读挂载的 `data/corpus`）下的语料删除时保留源文件与元数据，
  列表里显示为「已移出」（`chunks=0`），可调用 reingest 恢复；用户上传语料则连文件一起删干净。

### 3.2 访问控制（可选）

`/api/corpus` 会改动知识库，默认**不校验**。部署到可被外人访问的地址时：

```bash
# backend/.env（或根 .env —— compose 通过 env_file 注入容器）
CORPUS_WRITE_TOKEN=一个足够长的随机串
# frontend/.env.development（前端构建期变量，值要与上面一致）
VITE_WORKBENCH_TOKEN=同一个随机串
```

配置后所有语料接口都要求请求头 `X-Workbench-Token` 匹配，不匹配返回 403。
留空即保持"内网免鉴权"，老部署行为完全不变（`tests/test_corpus.py::TestWorkbenchToken` 钉住了这一点）。

维护提醒：

- 新增语料若带来新的事项名，需同步 `app/services/rag.py::ENTITY_HINTS`，否则相关问题会被判成「没说清办什么」而走候选引导；
- 批量增删语料会改变相关性分分布，需重跑 `scripts/calibrate_gate.py` + `scripts/probe_gate.py` 复核闸门阈值；
- `data/uploads/` 是运行期产物，已在 `.gitignore` 中排除（内置语料 `data/corpus` 必须入库）。

`GET /api/chat` 返回字段说明：

```json
{
  "answer": "面向群众的自然语言回答（Markdown）",
  "material_list": {
    "title": "事项名称", "department": "受理部门", "legal_time": "承诺时限",
    "fee": "收费标准", "channel": "办理渠道",
    "required": [{ "name": "材料名称", "desc": "说明", "count": "份数" }],
    "optional": [], "steps": [], "tips": []
  },
  "sources": [{ "doc_name": "《XXX》", "section": "必备材料", "snippet": "...", "score": 0.78 }]
}
```

## 四、RAG 链路设计

```
用户问题
  ↓ sanitize_question（控制字符过滤、URL 去除、超长截断 ≤1000 字）
问题向量化（Embedding）
  ↓
自适应融合检索：问题含政务术语 → 向量 0.45 + BM25 0.55；纯口语 → 只用向量（同文档同章节去重）
  ↓
相关性闸门（以向量语义为主）：vec ≥ VECTOR_MIN_SCORE
   或 (kw ≥ KEYWORD_MIN_SCORE 且 融合分 ≥ FUSED_MIN_SCORE)
  ↓ 未通过 → 直接返回"知识库暂无该业务相关政策，请咨询线下政务窗口"（拒绝编造）
泛问引导（引导，非拒答）：问题里没有业务实体词，或 Top-1 向量分 < VAGUE_VECTOR_MAX
  ↓ 命中 → 列出最相近的候选事项让用户确认，避免直接甩一份错误事项的材料清单

阈值随 Embedding 模型走（**换模型/扩语料必须重标**）：

| Embedding | 语料 | 标准问法 | 口语化泛问 | 域外 | `VECTOR_MIN_SCORE` / `VAGUE_VECTOR_MAX` |
| --- | --- | --- | --- | --- | --- |
| qwen3.7-text-embedding-flash（1024 维） | 33 篇 / 853 片段 | 0.709~0.968 | 0.428~0.836 | 0.331~0.353 | **0.45 / 0.50** |
| tongyi-embedding-vision-flash（768 维） | 12 篇 / 580 片段 | 0.830~0.927 | 0.708~0.911 | 0.576~0.716 | 0.73 / 0.78 |
结构化章节补全：在命中文档内定向召回 必备材料/可选材料/办理流程/受理部门/承诺时限/收费标准/温馨提示
  ↓
上下文组装：历史对话（最近 5 轮，超 3000 字从最早一轮丢弃）+ 召回原文 + 约束 Prompt
  ↓
大模型生成（temperature=0.2，强制 JSON 输出 answer + material_list）
  ↓ 调用失败 → 自动退化为抽取式回答，保证服务可用
结构校验（MaterialList）→ 写入 chat_history → 返回前端
```

**关键设计点**

| 设计 | 说明 |
| --- | --- |
| 上下文头（chunk headers） | 每个文本块前追加"文档标题 + 章节名"，使"社保卡需要什么材料"能命中材料章节 |
| 自适应融合检索 | 哈希/通用 Embedding 语义能力有限，融合 BM25 保证政务术语精确匹配；但**口语化泛问的 BM25 全是单二元组噪声**，会把噪声文档顶到 Top-1，因此"关键词不够强时只按向量排序" |
| 意图感知重排 | `实施依据/设定依据` 大段罗列法规名称，是"关键词磁铁"，会把 `材料清单`/`办理流程` 挤到后面；按问题意图给章节加权、给依据类降权后，材料类问题 Top1 才回到 `材料清单` |
| 向量主导的相关性判定 | 以向量余弦为主判据（口语化泛问只能靠语义匹配），术语强命中作兜底；口语化不再被整体判成"域外" |
| 泛问引导 | 没说清办什么时列出候选事项让用户确认 —— 是"引导"而不是"拒答"，避免硬答一个错误事项 |
| 结构化章节补全 | 办事类问题定向召回要素章节，保证材料清单字段不缺失 |
| 材料表行结构还原 | PDF 会把单元格拆成多行，按「行号 → 名称行 → 原件/复印件标记行」收口，避免抽出审查标准等噪声 |
| 抽取式兜底 | 无 API Key 时按章节优先级组织答案，零成本、零幻觉 |
| 全链路降级 | PostgreSQL/MySQL→SQLite、Milvus/Chroma→内存向量库、LLM→抽取式，任一缺失都不影响启动 |

## 五、配置说明（.env）

| 分类 | 关键项 | 说明 |
| --- | --- | --- |
| 数据库 | `DB_TYPE` `DB_HOST` `DB_PORT` | `postgresql`（默认，完整栈容器 gov-postgres 映射到本机 5432）/ `mysql` / `sqlite`；关系库不可达自动降级 SQLite |
| 向量库 | `VECTOR_STORE` | `milvus`（默认，完整栈容器 gov-milvus 映射到本机 **19531**，避开宿主 19530）/ `chroma` / `memory` |
| 向量维度 | `VECTOR_DIM` | 必须与 Embedding 一致：`hash` = 1024；`qwen3.7-text-embedding-flash` / `text-embedding-v3` = **1024**；`tongyi-embedding-vision-flash` = 768；`qwen3-vl-embedding` = **2560** |
| Embedding | `EMBEDDING_PROVIDER` | `hash`（离线）/ `openai` / `dashscope` / `dashscope_native` |
| 大模型 | `LLM_PROVIDER` | `extractive`（离线兜底）/ `openai` / `dashscope` |
| RAG | `TOP_K` `VECTOR_MIN_SCORE` `KEYWORD_MIN_SCORE` `FUSED_MIN_SCORE` `VAGUE_VECTOR_MAX` | 召回 4；向量主判据 **0.45**（1024 维）/ 0.73（768 维）、BM25 绝对分 44.3、融合兜底 0.62、泛问引导 0.60 / 0.78（**换 Embedding 模型或扩语料必须用 `scripts/calibrate_gate.py` + `scripts/probe_gate.py` 重新标定**） |
| 上下文 | `MAX_HISTORY_TURNS` `MAX_CONTEXT_CHARS` | 历史 5 轮、上下文 3000 字 |
| 预处理 | `CHUNK_SIZE` `CHUNK_OVERLAP` `DOCS_DIR` | 块大小 500、重叠 100 |

接入真实模型只需配置密钥（以本机已验证的 qwen3.7-text-embedding-flash + qwen3.8-flash 为例）：

```bash
# .env
EMBEDDING_PROVIDER=dashscope          # OpenAI 兼容文本向量接口（单请求上限 20 条，代码已分批）
VECTOR_DIM=1024                       # qwen3.7-text-embedding-flash 默认维度
LLM_PROVIDER=dashscope
DASHSCOPE_MODEL=deepseek-v4.1-flash
DASHSCOPE_API_KEY=sk-xxxxxxxx
LLM_TIMEOUT=300
LLM_ENABLE_THINKING=true   # deepseek-v4.1-flash 原生思考，服务端恒开
LLM_MAX_TOKENS=4096        # 思考模式下代码自动抬到 8192（思考 token 计入 max_tokens）
LLM_THINKING_BUDGET=0      # 仅 qwen 系支持，deepseek 会忽略
```

> **注意**：当前模型 `deepseek-v4.1-flash` 是**原生思考模型**（响应里带 `reasoning_content`），
> 服务端**恒开思考链**——实测传 `enable_thinking=false` 仍返回思考内容，关不掉；
> 且不支持 `thinking_budget`（传了被忽略）。因此 `LLM_ENABLE_THINKING=true`、
> `LLM_THINKING_BUDGET=0`，靠 `max_tokens` 兜底（思考 token 计入 max_tokens，
> 代码在思考模式下自动抬到 8192，否则答案会被思考内容挤没）。
>
> 历史教训（qwen3.8 系列）：推理模型开启思考链时单轮可达 **185s**，会撞破 60s 超时并使
> 「已召回成功」的问题被误判为"知识库暂无该业务相关政策"。因此超时放宽到 300s
> （前端 axios 同步改 300000）。
> 即便如此仍失败，也不会返回空答案 —— `RAGService._fallback_answer()` 会降级为
> 抽取式作答并标注"⚠️ 当前大模型不可用"，避免把超时误报成"无该政策"。

> **注意**：`qwen3-vl-embedding` 是**多模态**模型，**不支持 OpenAI 兼容模式**（会返回 404），
> 必须走原生端点 `/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding`，
> 且一次只能提交一条内容 —— `DashScopeNativeEmbedding` 已用线程池并发处理。
> 若改用 `text-embedding-v3`，则 `EMBEDDING_PROVIDER=dashscope`、`VECTOR_DIM=1024`。

## 六、导入已有 RAG 管道的语料（预计算向量）

若你已用离线管道（抽取→清洗→分块→向量化→建库）产出过 `index.json`，可直接复用其向量，
**无需重新调用 Embedding 接口**：

```bash
python scripts/import_existing_vectors.py                  # 追加导入（默认跳过 GD00 索引清单）
python scripts/import_existing_vectors.py --reset          # 先清空向量库再导入
python scripts/import_existing_vectors.py --source <path>  # 指定 index.json
python scripts/import_existing_vectors.py --exclude ""     # 连索引清单一起导入
```

数据源格式：

```json
{ "model": "qwen3-vl-embedding", "dim": 2560, "count": 570,
  "items": [{ "id": "...", "text": "...",
              "embedding": [0.01, ...],
              "metadata": { "doc_id": "GD01_...", "chunk_index": 0, "char_len": 471 } }] }
```

脚本行为：

1. 校验 `dim` 与 `VECTOR_DIM` 一致；
2. 识别并归一化章节标题（基础信息 / 受理条件 / 材料清单 / 办理流程 / 收费信息 …），
   并**排除 PDF 表格列名**（材料名称、材料依据、材料形式、材料要求、材料下载、其他信息）
   —— 否则材料表会被误判成"其他信息"；
3. 正文级纠正：按特征词（法律法规名称/依据文号/原件/复印件…）修正导航块造成的标题错配；
4. 为每个片段追加「文档标题 + 章节」上下文头，提升跨章节问题召回；
5. 同步写入 PostgreSQL 的 `doc_meta` 表。

> 默认排除 `GD00_*`（管道生成的"文件索引清单"）：它罗列了全部文档名，
> 会把各类问题都吸引到同一篇上，实测会拉低准确率。

## 七、离线知识库预处理

```bash
python scripts/ingest.py                    # 导入 data/docs 全部文档
python scripts/ingest.py --file 政策.pdf     # 导入单个文件（支持 pdf/docx/txt/md）
python scripts/ingest.py --clear            # 清空向量库后重建
```

处理流程：文档加载（PDF/Word/TXT/Markdown）→ 文本清洗（页眉页脚、空白、重复行、控制字符）
→ 章节切分 → 重叠窗口分块（500 字 / 重叠 100）→ Embedding → 写入向量库 + `doc_meta` 表。

## 八、数据库

- PostgreSQL（默认）：`sql/schema_postgres.sql`
- MySQL：`sql/schema.sql`

两者均与《系统设计》第四章表结构严格一致：`session`、`chat_history`、`doc_meta`。
文档文本块与向量不入库，仅存于向量库（**Milvus** / Chroma / 内存向量库），通过 `doc_id` 关联。

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -c "CREATE DATABASE gov_qa;"
psql -h 127.0.0.1 -p 5433 -U postgres -d gov_qa -f sql/schema_postgres.sql
```

Milvus 集合结构（`gov_docs`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | VARCHAR(128) 主键 | 片段 ID |
| `doc_id` / `doc_name` / `section` / `source` | VARCHAR(512) | 溯源元数据 |
| `text` | VARCHAR(8192) | 含上下文头的片段正文 |
| `embedding` | FLOAT_VECTOR(2560) | 余弦相似度（COSINE + AUTOINDEX） |

## 九、接口测试

```bash
python scripts/test_api.py
```

覆盖：健康检查 → 创建会话 → 6 类问题（5 个域内 + 1 个域外）→ 材料清单完整性 → 历史查询 → 参数校验。
域外问题（如"今天天气怎么样"）应返回"知识库暂无该业务相关政策"，体现拒绝编造策略。
