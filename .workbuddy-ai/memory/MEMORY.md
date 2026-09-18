# MEMORY.md — 政明白 GovRAG 项目长期约定

## Git 远端（2026-09-18）

- 仓库：`https://github.com/mmmzzz0705/bigproject`（README 徽章已指向它）。
- 本机有**全局 URL 重写**：`url.https://ghfast.top/https://github.com/.insteadof https://github.com/`
  —— 所以 `git remote -v` 永远显示 ghfast.top 前缀，这是正常的镜像加速，不是配错。
- push 需要 GCM 交互授权（弹窗/浏览器），非交互 shell 里会一直等到超时（exit 124）。
  必须由主人在自己的终端里执行 `git push -u origin main` 完成登录。

## CI/CD（2026-09-17 起）

- 工作流：`.github/workflows/ci.yml`（backend-test / frontend-build / docker-build / smoke）、
  `cd.yml`（build-and-push 到 GHCR + appleboy SSH 部署）、`docker-compose.deploy.yml`
  （只覆盖 backend/frontend 的 `image:`）。部署细节见 `CI-CD配置说明.md`。
- 部署命令：`docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d`，
  镜像名走 `BACKEND_IMAGE` / `FRONTEND_IMAGE` 环境变量（`:?` 语法，忘传直接报错）。
- CI 跑 `python scripts/quality_gate.py`（ruff F,E9 + pytest），与本地同命令。
  CI 里 `backend/.env` 与根 `.env` 由 `.example` 现场生成（含密钥的文件不入库）。
- 后端测试**不需要** PG/Milvus：DB_HOST 留空即降级 SQLite + 内存向量库，integration 用例自 skip。

## 部署（2026-09-14 起）

- 一律 `docker-compose -f docker-compose.yml up -d`（gov-postgres / gov-milvus-etcd /
  gov-milvus-minio / gov-milvus / gov-backend / gov-frontend）。
- **弃用 `docker-compose.host.yml`**：宿主 `milvus-standalone`（v3.0.0 + 内嵌 etcd +
  Windows 绑定挂载）必踩两坑：重启 `panic: etcdserver: leader changed`、
  段文件路径差一层 `files/` → 永久卡 Loading(33%)、检索全 503。宿主 `bigpg:5433` 也不用。
- 端口：前端 8080 / 后端 8000 / PG 5432 / Milvus 19531（避开宿主 19530）/ MinIO 9001。
- 改后端或前端代码 → 加 `--build <service>`。改 `.env` → 必须 `--force-recreate`
  （`restart` 不重新注入 env）。换语料或换 Embedding 模型才需重灌：
  `docker exec gov-backend python scripts/ingest.py --dir /app/data/corpus --clear`
- 启动后 15~30s 就绪（backend 有 `depends_on: service_healthy` 自动等 Milvus）。
  验：`curl http://127.0.0.1:8080/api/health` → `doc_count` > 0（准确片段数看 `/api/corpus`）。
  注：Nginx 已设 `client_max_body_size 20m`，否则工作台上传 >1MB 会被 413 拦在网关层。
- 往容器同步代码（不想重建镜像时）：`docker cp backend/app/. gov-backend:/app/app/`
  **必须带 `/.`**，否则目标目录已存在会嵌套成 `/app/app/app`，接口 404 且极难看出原因。
  之后 `docker restart gov-backend`。
- 构建镜像时 pip 源不稳：清华偶发 `grpcio` 哈希校验失败、阿里云在容器内 DNS 解析失败。
  Dockerfile 已加 `ARG PIP_INDEX_URL`，可
  `PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple docker-compose build backend`；
  换源不行就原样重试（依赖层有缓存，第二次通常 2~3 分钟）。

## 质量门禁（2026-09-17 起）

- 提交前跑 `python scripts/quality_gate.py`（ruff F,E9 + pytest；`--with-frontend` 加前端构建）。
  失败退 1，可直接挂 CI。项目**不是 git 仓库、也没有 .github/workflows**，别去找 CI 配置。

## 工作台：语料自助增删（2026-09-17 新增）

- 入口：侧栏顶部「智能问答 / 工作台」切换；工作台页 = 统计卡 + 上传/粘贴 + 语料表格。
- 接口：`GET /api/corpus`、`POST /api/corpus/upload`、`POST /api/corpus/text`、
  `DELETE /api/corpus/{doc_id}`、`POST /api/corpus/{doc_id}/reingest`、
  `GET /api/corpus/{doc_id}/chunks?limit=`（切分预览，看每篇被切成什么，调 CHUNK_SIZE 用）。
- 目录约定：上传语料落 `backend/data/uploads`（**可写**）；内置语料 `backend/data/corpus`
  在 compose 里是 **`:ro` 挂载**，删不掉也不该删。origin 按"文件当前在哪个目录"实时判定，
  不入库（免得给 PG 和 SQLite 各写一遍迁移）。
- **删除语义**：上传语料 = 文件+元数据一起删；内置语料 = **只清向量，保留文件与 doc_meta 行**
  （列表里 `in_index=false`、可 reingest）。元数据删了就永远恢复不回来。
- **片段总数口径**：`total_chunks` 用 `sum(doc_stats().values())`，**不能用 `store.count()`** ——
  Milvus 是逻辑删除，`row_count` 仍算已删未 compaction 的行。
  所以 `/api/health` 的 `doc_count`（用 count()）会比 `/api/corpus` 的 `total_chunks` 偏大，
  这是正常的，**准确值以后者为准**。
- 幂等：`ingest_file` 写入前先 `_delete_existing(doc_id)`（doc_id 由文件名哈希而来）。
  同名上传 = 更新，不会留重复片段。
- **防顶替**：上传文件若与 `data/corpus` 内文件同名，落盘时自动改名（`xxx_上传.txt`）。
  doc_id 由文件名哈希而来，同名 = 覆盖内置基准语料的全部片段，且删了就无法 reingest。
- 覆盖入库失败时会明确报"旧片段已被移除"：幂等是先删旧片段再写入，中间失败旧语料就没了。
- 文档名优先级：**上传时填的 title > 文件名 > 正文首有效行**。`extract_title` 已跳过
  URL/页眉行（传 `qz.pdf` 曾把"指南地址:https://..."当标题）。用户上传的文件名常无语义，
  前端在文件名无中文或过短时会提醒填「语料名称」。
- 上传文件落在 `backend/data/uploads`，compose **显式挂载到宿主机**（不能只放 backend_data 卷，
  `down -v` 会连卷删掉）。
- 依赖：`python-multipart`（UploadFile 必需）；Nginx 已设 `client_max_body_size 20m`。
- **访问控制（可开关，默认关）**：`CORPUS_WRITE_TOKEN`（后端）+ `VITE_WORKBENCH_TOKEN`（前端）。
  留空 = 不校验，内网部署行为不变；填了之后 `/api/corpus` 全部接口要求请求头
  `X-Workbench-Token` 匹配，否则 403。实测：无凭证 403 / 错凭证 403 / 正确 200。
  注意前端未配置时 Vite 会把该分支静态折叠掉，产物里搜不到 header 名是**正常**的。

## 排查要点（踩过的坑）

1. 全线答"知识库暂无该业务政策"：先看 `/api/health` 的 `vector_store`（`memory` = 降级）
   与 `doc_count`；再看 `docker logs gov-backend | grep 大模型调用失败`（非空即已降级兜底）。
2. Milvus 卡 Loading：`docker logs gov-milvus | grep 'load segment failed'`；
   报 `invalid local path` = 存储布局不匹配，重灌救不回，只能换部署。
3. DashScope 401：先比 key 长度（`len()`），差 1 位 = `.env` CRLF 混进 `\r`，转 LF。
   判断 key 是否有效：打 `/compatible-mode/v1/embeddings` 返回 **404 model_not_supported
   说明 key 有效**（401 才是 key 问题）。
4. 本机 **没有 compose v2 插件**：必须写 `docker-compose`（带连字符）。
5. **401 最隐蔽成因**（2026-09-15）：本机 Machine 级残留失效旧 `DASHSCOPE_API_KEY`（117 位）。
   compose 的 `${VAR}` 插值优先级是「持久环境变量 > `.env`」。已加固：backend 用
   `env_file: [.env]`，密钥不走 `${}`。治本：管理员 PowerShell
   `[Environment]::SetEnvironmentVariable('DASHSCOPE_API_KEY',$null,'Machine')`。
6. 扩语料后必须同步 `rag.py::ENTITY_HINTS`；`_is_vague` 第一条件缺词 → 该答不答。
7. OpenAI 兼容 Embedding 单请求上限 20 条：`OpenAICompatEmbedding` 已按 `BATCH_SIZE=10`
   分片 + 并发 + 退避，别改回整篇提交。
8. 答案被砍半：LLM 在 JSON 正文写英文双引号 → `json.loads` 失败。
   `llm._rescue_answer` 已按结构边界定结尾（**取第一个匹配**，取最后一个会把整段 JSON
   当答案吐给前端）。排查：打桩打印 raw 长度，raw 完整而 answer 短 = 解析层截断，别调 max_tokens。
9. `--force-recreate` 后**必须回读容器 env**：
   `docker exec gov-backend env | grep -E "SCORE|VAGUE|DIM|EMBED_MODEL|DASHSCOPE_MODEL"`。
   真事故：root `.env` 被写成 `VECTOR_MIN_SCORE=2.0` / `VAGUE_VECTOR_MAX=0.0`，容器照单全收。

## 检索闸门（2026-09-15 标定：qwen3.7-text-embedding-flash / 1024 维 / 853 片段）

- 排序：关键词池最大值 < `KEYWORD_MIN_SCORE` 时纯按向量分排（口语化术语无重叠，
  BM25 只有噪声）；术语强时 0.45 向量 + 0.55 BM25。
- 闸门 `_is_relevant`：`vec >= VECTOR_MIN_SCORE` **或**（`kw >= KEYWORD_MIN_SCORE` 且
  融合分 `>= FUSED_MIN_SCORE`）。放行但"没说清办什么" → `VAGUE_VECTOR_MAX` 走候选引导，不硬答。
- 现值：`VECTOR_MIN_SCORE=0.45`、`KEYWORD_MIN_SCORE=44.3`、`FUSED_MIN_SCORE=0.62`、
  `VAGUE_VECTOR_MAX=0.50`。
  `VECTOR_MIN` 故意低于标定推荐 0.752 —— 0.752 会把口语化泛问全挡门外（它们 kw≈0）。
- 实测分布：域外 0.335~0.356｜像政务未收录 0.501~0.739｜口语化 0.418~0.838｜标准 0.665~0.973。
- **改语料也要重标闸门**（补 FAQ 后域外 kw 从 35.2 涨到 42.9）。工具：
  `scripts/calibrate_gate.py`（标准问法）+ `probe_gate.py`（口语化/域外）+ `scripts/qa_smoke.py`（端到端）。

## `ENTITY_HINTS` 口径（双向过一遍）

它是"我们有底气直接答的业务清单"，**不是政务词汇表**。两类词都不能放：
语料未覆盖的事项词（曾放 `低保`/`残疾` → 硬答编造）；通用后缀（曾放 `许可证` →
「烟草专卖零售许可证」按《食品经营许可证核发》硬答）。缺词 → 过度保守；多词 → 过度自信。

## 材料表两种版式（`material.py`）

- 版式 A 表格式「材料名称 / 原件：/ 复印件：」→ `_extract_rows()`。
- 版式 B 条目式「应提交材料：1.…2.…」→ `_extract_numbered()`（每编号只取第一句；
  丢弃「、（）月」开头残片；判定前先 `re.sub(r"\s+","",name)` 处理 PDF 断行）。

## 环境事实

- 语料：`backend/data/corpus/` **33 篇**广东政务指南（GD01~GD32）→ **853 片段 / 1024 维**。
  Embedding = `qwen3.7-text-embedding-flash`（`EMBEDDING_PROVIDER=dashscope`，OpenAI 兼容）。
  换 Embedding 模型 → 必须改 `VECTOR_DIM` + 重灌（Milvus 维度不一致会删集合重建）+ 重标闸门。
- 两份 `.env` 都要改：`backend/.env`（应用读）、根 `.env`（compose 读）。
- **换模型/调阈值要改 6 处**（`tests/test_env_sync.py` 钉死）：
  `backend/.env`、`backend/.env.example`、`.env`、`.env.docker.example`、
  `docker-compose.yml`、`docker-compose.host.yml`。
  校验键（`test_env_sync.CRITICAL` 共 7 个）：`VECTOR_DIM` / `DASHSCOPE_EMBED_MODEL` /
  `VECTOR_MIN_SCORE` / `KEYWORD_MIN_SCORE` / `DASHSCOPE_MODEL` / `FUSED_MIN_SCORE` /
  `VAGUE_VECTOR_MAX`。加新阈值键要进这个元组。
- 自检：`.venv\Scripts\python.exe -m pytest tests/test_env_sync.py`（18 passed）、
  `.venv\Scripts\python.exe scripts/check_env.py --skip-llm`（5/5，doc_meta=33、853 片段、dim=1024）。
- 密钥只写 `.env`（已 gitignore），不进文档。

## 大模型：`deepseek-v4.1-flash`（2026-09-16 从 `qwen3.8-2.4t-a95b` 切过来）

- **原生思考模型**：服务端**恒开思考链**，实测传 `enable_thinking=false` 仍返回
  `reasoning_content`，关不掉；**不支持 `thinking_budget`**（传了被忽略，返回 200）。
  故 `LLM_ENABLE_THINKING=true` + `LLM_THINKING_BUDGET=0`。
- 思考 token 计入 `max_tokens`：`llm.generate` 在思考分支自动抬到
  `THINKING_MIN_TOKENS=8192`（沿用 4096 会把答案挤没）。
- `_thinking_body()` 已按模型族过滤：`thinking_budget` 只对 `qwen*` 下发。
- 实测：标准问法 17~22s、口语化 11s，答案 400~560 字符，材料卡片正常，域外正常拒答。
- **换 LLM 是轻操作**：只改 6 份配置的 `DASHSCOPE_MODEL` + `--build backend`，
  不重灌向量库、不改 `VECTOR_DIM`、不重标闸门。同步点还含两份 README（共 8 处）。
- 生效判断：`/api/health` 的 `llm_provider` 显示 `dashscope:<模型名>`。
  **验收不能只看 health**：health 绿 + 有答案也可能是抽取式兜底 → 必须
  `docker logs gov-backend | grep 大模型调用失败` 为空。

## 补语料动作清单（2026-09-15 补 GD32 走过）

1. 取原文：`https://static.gdzwfw.gov.cn/portal/wk-pdf?code=<实施编码>&template=guide-v2`
   curl 下载（部分 code 会 500，换地市重试）。首页是 SPA，静态抓不到。
2. `pypdf` 提文本（.venv 里有），PDF 表格断行需手工整理。
3. 落盘 `GDxx_事项名_广东政务网.txt`，结构对齐：基础信息 / 受理范围 / 办理流程 /
   材料清单 / 收费标准 / 设定依据 / **常见问题 / 温馨提示**（GD12 起必有，会抬高域外 kw 分）/
   办理窗口 / 法律救济。材料清单须写成「材料名称 / 原件：1 / 复印件：0 / 纸质 / 必要」。
4. 补 `rag.py::ENTITY_HINTS`（只加具体词，不加"卡""证"这类通用后缀）。
5. 重灌（853 片段约 6 分钟）→ `--build backend` → 回读 `doc_count` → 跑 `probe_gate.py`
   复核域外最高分 / 口语化最低分仍夹住 `VECTOR_MIN`。
