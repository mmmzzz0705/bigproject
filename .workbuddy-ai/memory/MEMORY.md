# MEMORY.md — 政明白 GovRAG 项目长期约定

## 项目与交付物

- 项目：政明白（GovRAG 政务智能问答与办事引导系统）。小组：第六组；项目经理：麦少彤；
  成员：陈梓烽、贺悦洋、黎敬浩。
- 文档：`第六组_政明白_可行性分析报告.docx`（V1.1，2026-09-13）→ 后续 SRS 的元数据基准。
  另有 `可行性报告.md`、`学术论文_政明白GovRAG.md`、`工作台功能与质量说明.md`。
- Git：`https://github.com/mmmzzz0705/bigproject`。本机有全局 URL 重写
  （`ghfast.top` 镜像），`git remote -v` 显示 ghfast 前缀是正常的。
  push 需 GCM 交互授权，非交互 shell 会一直等到超时（exit 124）——必须由主人自己 push
  （首次已完成，凭据已缓存，之后 `git push` 不再弹窗）。
- **日常同步一条命令**：`scripts\push.bat "提交说明"`（门禁 → add → commit → push，
  门禁不过直接中止；首参 `nogate` 可跳过门禁）。脚本内容保持 ASCII，别写中文进去。
- push 是**追加**不是覆盖，只有 `--force` 才覆盖。GitHub 不会自动同步本地改动。

## 部署（2026-09-14 起）

- 一律 `docker-compose -f docker-compose.yml up -d`（gov-postgres / gov-milvus-etcd /
  gov-milvus-minio / gov-milvus / gov-backend / gov-frontend）。
- **弃用 `docker-compose.host.yml`**：宿主 milvus-standalone（v3.0.0 + 内嵌 etcd +
  Windows 绑定挂载）必踩：重启 `panic: etcdserver: leader changed`、段文件路径差一层
  `files/` → 永久卡 Loading(33%)、检索全 503。宿主 `bigpg:5433` 也不用。
- 端口：前端 8080 / 后端 8000 / PG 5432 / Milvus 19531 / MinIO 9001。
- 改代码 → 加 `--build <service>`；改 `.env` → 必须 `--force-recreate`；
  换语料或换 Embedding 模型才重灌：`docker exec gov-backend python scripts/ingest.py --dir /app/data/corpus --clear`。
- 启动 15~30s 就绪。验：`curl http://127.0.0.1:8080/api/health` → `doc_count > 0`
  （准确片段数看 `/api/corpus` 的 `total_chunks`）。Nginx 已设 `client_max_body_size 20m`。
- 同步代码不想重建镜像：`docker cp backend/app/. gov-backend:/app/app/` **必须带 `/.`**
  （否则嵌套成 `/app/app/app`，接口 404），再 `docker restart gov-backend`。
- 构建 pip 源不稳：清华偶发 grpcio 哈希失败、阿里云容器内 DNS 失败。
  `PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple docker-compose build backend`。

## CI/CD（2026-09-17 起）

- `.github/workflows/ci.yml`（backend-test / frontend-build / docker-build / smoke）、
  `cd.yml`（GHCR + SSH 部署）、`docker-compose.deploy.yml`（只覆盖 image:）。
  细节见 `CI-CD配置说明.md`。
- 部署命令：`docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d`，
  镜像名走 `BACKEND_IMAGE` / `FRONTEND_IMAGE`（`:?` 语法，忘传直接报错）。
- CI 跑 `python scripts/quality_gate.py`（ruff F,E9 + pytest）。后端测试不需要 PG/Milvus：
  DB_HOST 留空即降级 SQLite + 内存向量库，integration 自 skip。含密钥的 `.env` 不入库，
  CI 现场由 `.example` 生成。
- 质量门禁：提交前跑 `python scripts/quality_gate.py`（`--with-frontend` 加前端构建），失败退 1。

## 工作台：语料自助增删（2026-09-17）

- 入口：侧栏「智能问答 / 工作台」切换；工作台 = 统计卡 + 上传/粘贴 + 语料表格。
- 接口：`GET /api/corpus`、`POST /api/corpus/upload`、`POST /api/corpus/text`、
  `DELETE /api/corpus/{doc_id}`、`POST /api/corpus/{doc_id}/reingest`、
  `GET /api/corpus/{doc_id}/chunks?limit=`（切分预览）。
- 目录：上传落 `backend/data/uploads`（可写，且 compose 显式挂宿主机）；
  内置 `backend/data/corpus` 是 `:ro` 挂载，删不掉也不该删。origin 按文件当前所在目录实时判定。
- **删除语义**：上传语料 = 文件+元数据一起删；内置语料 = 只清向量，保留文件与 doc_meta
  （列表 `in_index=false`、可 reingest）。元数据删了永远恢复不回来。
- **片段总数**用 `sum(doc_stats().values())`，**不能用 `store.count()`**（Milvus 逻辑删除，
  row_count 仍算已删行）。故 health 的 doc_count 偏大，准确值以 `/api/corpus` 为准。
- 幂等：写入前先 `_delete_existing(doc_id)`（doc_id = 文件名哈希），同名上传 = 更新。
  覆盖失败会明确报"旧片段已被移除"。
- **防顶替**：上传与 `data/corpus` 同名 → 自动改名 `xxx_上传.txt`。
- 文档名优先级：上传填的 title > 文件名 > 正文首有效行（extract_title 已跳过 URL/页眉行）。
- 访问控制（默认关）：`CORPUS_WRITE_TOKEN` + `VITE_WORKBENCH_TOKEN`，填了就要求请求头
  `X-Workbench-Token`，否则 403。前端未配置时 Vite 会静态折叠该分支，产物里搜不到 header 是正常的。

## 检索闸门（2026-09-15 标定：1024 维 / 853 片段）

- 排序：关键词池最大值 < `KEYWORD_MIN_SCORE` 时纯按向量分排；术语强时 0.45 向量 + 0.55 BM25。
- 闸门：`vec >= VECTOR_MIN_SCORE` **或**（`kw >= KEYWORD_MIN_SCORE` 且融合分 `>= FUSED_MIN_SCORE`）。
  放行但没说清办什么 → `VAGUE_VECTOR_MAX` 走候选引导，不硬答。
- 现值：`VECTOR_MIN_SCORE=0.45`、`KEYWORD_MIN_SCORE=44.3`、`FUSED_MIN_SCORE=0.62`、
  `VAGUE_VECTOR_MAX=0.50`。VECTOR_MIN 故意低于标定推荐 0.752（否则口语化泛问全被挡）。
- 实测分布：域外 0.335~0.356｜像政务未收录 0.501~0.739｜口语化 0.418~0.838｜标准 0.665~0.973。
- **改语料也要重标**（补 FAQ 后域外 kw 从 35.2 涨到 42.9）。工具：`scripts/calibrate_gate.py`、
  `probe_gate.py`、`scripts/qa_smoke.py`。

## 关键口径

- `ENTITY_HINTS` = "我们有底气直接答的业务清单"，不是政务词汇表。不放语料未覆盖事项词
  （曾放 低保/残疾 → 编造），也不放通用后缀（曾放 许可证 → 张冠李戴）。
- `material.py` 两种版式：A 表格式「材料名称/原件:/复印件:」→ `_extract_rows()`；
  B 条目式「应提交材料：1.…」→ `_extract_numbered()`（每编号只取第一句，先去空白再判）。

## 环境事实

- 语料：`backend/data/corpus/` **33 篇**广东政务指南 → **853 片段 / 1024 维**。
  Embedding = `qwen3.7-text-embedding-flash`（OpenAI 兼容，批 10 条 / 并发 6 / 超时 30s）。
  换 Embedding → 改 `VECTOR_DIM` + 重灌（Milvus 维度不一致会删集合重建）+ 重标闸门。
- 两份 `.env` 都要改：`backend/.env`（应用读）、根 `.env`（compose 读）。
- **换模型/调阈值要改 6 处**（`tests/test_env_sync.py` 钉死）：`backend/.env`、
  `backend/.env.example`、`.env`、`.env.docker.example`、`docker-compose.yml`、
  `docker-compose.host.yml`。校验键（`test_env_sync.CRITICAL` 7 个）：`VECTOR_DIM` /
  `DASHSCOPE_EMBED_MODEL` / `VECTOR_MIN_SCORE` / `KEYWORD_MIN_SCORE` / `DASHSCOPE_MODEL` /
  `FUSED_MIN_SCORE` / `VAGUE_VECTOR_MAX`。新增阈值键要进这个元组。
- 自检：`.venv\Scripts\python.exe -m pytest tests/test_env_sync.py`（18 passed）、
  `scripts/check_env.py --skip-llm`（5/5）。密钥只写 `.env`，不进文档。

## 大模型：`deepseek-v4.1-flash`（2026-09-16 从 qwen3.8 切来）

- **原生思考模型**：服务端恒开思考链，`enable_thinking=false` 无效；不支持 `thinking_budget`
  （传了被忽略）。故 `LLM_ENABLE_THINKING=true` + `LLM_THINKING_BUDGET=0`。
- 思考 token 计入 max_tokens：`llm.generate` 思考分支自动抬到 `THINKING_MIN_TOKENS=8192`。
- 实测：标准问法 17~22s、口语化 11s，答案 400~560 字符，材料卡片正常，域外正常拒答。
- 换 LLM 是轻操作：只改配置里的 `DASHSCOPE_MODEL`（同步点含两份 README，共 8 处）+ `--build backend`，
  不重灌、不改 VECTOR_DIM、不重标闸门。
- 验收不能只看 health（health 绿 + 有答案也可能是抽取式兜底）→ 必须
  `docker logs gov-backend | grep 大模型调用失败` 为空。

## 排查要点（踩过的坑）

1. 全线答"知识库暂无该业务政策"：看 health 的 `vector_store`（`memory` = 降级）与 doc_count；
   再看 `docker logs gov-backend | grep 大模型调用失败`。
2. Milvus 卡 Loading：`docker logs gov-milvus | grep 'load segment failed'`；
   `invalid local path` = 存储布局不匹配，重灌救不回，只能换部署。
3. DashScope 401：先比 key 长度（差 1 位 = `.env` CRLF 混进 `\r`，转 LF）。
   打 `/compatible-mode/v1/embeddings` 返回 **404 model_not_supported 说明 key 有效**（401 才是 key 问题）。
4. 本机**没有 compose v2 插件**：必须写 `docker-compose`（带连字符）。
5. **401 最隐蔽成因**：Machine 级残留失效旧 `DASHSCOPE_API_KEY`；compose `${VAR}` 插值优先级
   「持久环境变量 > .env」。已加固 backend 用 `env_file: [.env]`。治本：管理员 PowerShell
   `[Environment]::SetEnvironmentVariable('DASHSCOPE_API_KEY',$null,'Machine')`。
6. 答案被砍半：LLM 在 JSON 正文写英文双引号 → `json.loads` 失败。`llm._rescue_answer` 按结构
   边界定结尾（**取第一个匹配**）。排查：打桩看 raw 长度，raw 完整而 answer 短 = 解析层截断，别调 max_tokens。
7. `--force-recreate` 后**必须回读容器 env**：
   `docker exec gov-backend env | grep -E "SCORE|VAGUE|DIM|EMBED_MODEL|DASHSCOPE_MODEL"`。

## 「语料全部显示已移出」= Milvus 元数据丢了（2026-09-18 首次遇到）

- `doc_meta` 表**只有 4 列**（doc_id/doc_name/source/upload_time），**没有 in_index/chunks**
  → 这俩是 `doc_stats()` 从 Milvus 实时算的（`corpus.py:214` `in_index = chunks>0`）。
  「已移出」不是标记位，是 Milvus 里真没向量。**别去改数据库，改不了。**
- 根因：Milvus 集合的 etcd 元数据与 MinIO 对象存储不一致 → `has_collection('gov_docs')` 返回
  false → 后端新建空集合 → `AUTO_INGEST_ON_STARTUP=false` **不自动重灌** → 空库。
  证据：MinIO 里残留旧 collectionID 的 insert_log/delta_log，Milvus 日志报
  `collection not found[collection=<旧ID>]`。
- 修复只有一条：重灌。
  `docker exec -w /app gov-backend python scripts/ingest.py --dir /app/data/corpus --clear`
- 排查三步：① `/api/corpus` 看 total_chunks / in_index（**别信 health 的 doc_count**）；
  ② 后端日志 grep `DELETE /api/corpus` 为空 = 排除人工删除；
  ③ MilvusClient 按 doc_id 聚合看真实剩几个 doc。
- MinIO 侧时间线还原：`docker exec gov-milvus-minio ls -laR /minio_data/a-bucket/files/delta_log`
  （删除记录）+ `.../insert_log`（写入记录）。**该镜像里 `find` 不可靠**（返回 0 文件），
  必须 `ls -laR`；挂载点是 `/minio_data`，不是 `/data`。
- PG 连接：host=gov-postgres port=5432 db=**gov_qa** user=**postgres** pwd=123456。
- **隐患**：根因（etcd/MinIO 不一致）未根治，可能复发。复发两次就 `docker-compose down -v`
  彻底重建 Milvus 栈再重灌。

## 补语料动作清单（2026-09-15 补 GD32 走过）

1. 取原文：`https://static.gdzwfw.gov.cn/portal/wk-pdf?code=<实施编码>&template=guide-v2`
   curl 下载（部分 code 会 500，换地市重试）；首页是 SPA，静态抓不到。
2. `pypdf` 提文本，PDF 表格断行需手工整理。
3. 落盘 `GDxx_事项名_广东政务网.txt`，结构对齐：基础信息 / 受理范围 / 办理流程 / 材料清单 /
   收费标准 / 设定依据 / **常见问题 / 温馨提示**（GD12 起必有，会抬高域外 kw 分）/ 办理窗口 / 法律救济。
   材料清单写成「材料名称 / 原件：1 / 复印件：0 / 纸质 / 必要」。
4. 补 `rag.py::ENTITY_HINTS`（只加具体词）。
5. 重灌（853 片段约 6 分钟）→ `--build backend` → 回读 doc_count → 跑 `probe_gate.py` 复核。
