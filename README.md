# 政明白（GovRAG）· 政务智能问答与办事引导系统

[![CI](https://github.com/mmmzzz0705/bigproject/actions/workflows/ci.yml/badge.svg)](https://github.com/mmmzzz0705/bigproject/actions/workflows/ci.yml)
[![CD](https://github.com/mmmzzz0705/bigproject/actions/workflows/cd.yml/badge.svg)](https://github.com/mmmzzz0705/bigproject/actions/workflows/cd.yml)

> **政明白** —— 让群众把办事流程「整明白」：有据可答、无据拒答、全程可溯源。
> 英文代号 **GovRAG**（Government Retrieval-Augmented Generation），容器沿用 `gov-` 前缀。

对应《系统设计》四层架构的完整实现：前端展示层、后端服务层、AI 应用层、数据存储层。

```
D:\group6
├─ frontend/            Vue 3 + Vite 前端展示层
├─ backend/             FastAPI 后端服务层 + AI 应用层
├─ docker-compose.yml   PostgreSQL + Milvus + 后端 + 前端 一键部署
└─ .env.docker.example  部署环境变量示例
```

## 一、四层架构实现对照

| 设计章节   | 实现位置                                                                | 状态 |
| ------ | ------------------------------------------------------------------- | -- |
| 前端展示层  | `frontend/`（Vue 3 + Vite + Axios）                                   | ✅  |
| 后端服务层  | `backend/app/`（FastAPI：参数校验、跨域、会话管理、异常捕获）                           | ✅  |
| AI 应用层 | `backend/app/services/`（预处理 / 检索 / **重排** / 生成，支持 LangChain 链）      | ✅  |
| 数据存储层  | **PostgreSQL**（`sql/schema_postgres.sql`）+ **Milvus** 向量库           | ✅  |
| 接口设计   | `POST /api/session/create`、`POST /api/chat`、`GET /api/chat/history` | ✅  |
| 安全与容错  | 输入过滤、超时中断、相关性闸门、拒绝编造、全链路降级                                          | ✅  |
| 部署设计   | `docker-compose.yml` + 前后端 Dockerfile                               | ✅  |

### 当前运行环境（本机已部署的服务）

> 2026-09-14 起改用 `docker-compose.yml` 完整栈（宿主 `milvus-standalone` 那套已弃用，
> 原因见第四节「已知问题」）。

| 组件         | 地址                   | 说明                                                   |
| ---------- | -------------------- | ---------------------------------------------------- |
| PostgreSQL | `127.0.0.1:5432`     | 容器 `gov-postgres`，库 `gov_qa`，用户 `postgres`           |
| Milvus     | `127.0.0.1:19531`    | 容器 `gov-milvus`（v2.4.13 + etcd + MinIO），集合 `gov_docs`（853 片段 / 1024 维） |
| Embedding  | DashScope OpenAI 兼容接口  | `qwen3.7-text-embedding-flash`（1024 维）               |
| 大模型        | DashScope 兼容模式（推理模型） | `deepseek-v4.1-flash`                                |

## 二、本地开发启动

### 一键启动（推荐）

```bash
scripts\start.bat      # Windows：自动装依赖 → 起后端 :8000 → 起前端 :5173
scripts\stop.bat       # 停止（按端口 8000 / 5173 杀进程）
```

脚本会**优先使用 `backend\.venv`**（存在就直接用，不存在才回退到 PATH 上的 python 并提示建 venv），  
避免"pip 装到 A、uvicorn 跑 B"这类问题。首次使用请先按下面「手动启动」第 0 步建好虚拟环境。

> 注意：若 Docker 版后端已在跑（占用 8000），先 `docker-compose stop backend`  
> 再本地启动，否则端口冲突。

启动前可先跑依赖自检，一次看清 PostgreSQL / Milvus / Embedding / 大模型 是否可用：

```bash
cd backend
.venv\Scripts\python.exe scripts/check_env.py             # 全量（会真实调用大模型）
.venv\Scripts\python.exe scripts/check_env.py --skip-llm  # 跳过大模型调用
```


### 手动启动

> **先建虚拟环境，别直接用系统 Python。** 本项目依赖 fastapi / pymilvus / psycopg2 等，  
> 装到全局 Python 里既容易和别的项目打架，也容易出现"明明装了却 import 不到"——  
> 因为 `python -m uvicorn` 用的解释器和你 `pip install` 的那个根本不是同一个。  
> 典型报错：`ModuleNotFoundError: No module named 'fastapi'`。

```bash
# 0. 建虚拟环境（只需一次）
cd backend
python -m venv .venv          # ← 前提：这个 python 是 3.12 / 3.13，见下方警告
```

> ⚠️ **两个必看的坑，都真实踩过：**
>
> **① 别用 Python 3.14。** `pymilvus` / `chromadb` / `pydantic-core` 在 3.14 上
> 没有预编译包（cp314），会走源码构建并大概率装坏。先 `python -V` 确认版本，
> 不是 3.12/3.13 就显式指定解释器：
>
> ```bash
> # 先看本机有哪些可用版本
> py -0p                     # Windows 官方安装版
> uv python list             # 若装了 uv
>
> # 推荐：用 uv（本机已装，0.12.13）
> uv venv --python 3.12 --seed .venv
>
> # 或者直接用 3.12 解释器全路径建（--seed 的作用是顺带装上 pip）
> "C:\Users\<你>\AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none\python.exe" -m venv .venv
> ```
>
> 注意 `py -3.12` **可能不可用** —— 只有官方安装版才会注册到 py 启动器，
> uv 管理的解释器虽然出现在 `py -0p` 列表里，但 `py -3.12` 会报
> `No suitable Python runtime found`。这种情况用上面两条命令之一。
>
> **② 重建 venv 前必须先删掉旧目录。** `python -m venv .venv` 作用在**已存在**的
> `.venv` 上时**不会清空 `site-packages`**，只改配置文件。后果非常隐蔽：
> 旧的 3.12 二进制留在原地，pip 按版本号判断"已满足"不会重装，
> 于是 3.14 的解释器去加载 cp312 的 `.pyd`，报：
>
> ```
> ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'
> ```
>
> ```bash
> # 正确做法：先删干净再建
> rmdir /s /q .venv      # Windows
> rm -rf .venv           # Git Bash / macOS / Linux
> ```
>
> **怎么一眼看出 venv 是哪个 Python 建的**：看 `.venv\pyvenv.cfg` 里的 `home` / `version`，
> 以及 `site-packages\pydantic_core\` 下 `.pyd` 文件名的 `cp3XX` 后缀 ——
> 后缀必须和 `pyvenv.cfg` 的版本一致，不一致就是这个坑。

**进入虚拟环境**（每次开新终端都要做）：

| 终端                       | 命令                                                                  |
| ------------------------ | ------------------------------------------------------------------- |
| Windows CMD              | `.venv\Scripts\activate.bat`                                        |
| Windows PowerShell       | `.\.venv\Scripts\Activate.ps1`                                      |
| Git Bash / macOS / Linux | `source .venv/Scripts/activate`（macOS/Linux 是 `.venv/bin/activate`） |

> PowerShell 若报「禁止运行脚本」，先执行一次：  
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

激活成功后命令行前面会出现 `(.venv)`。**不想激活也行**——直接用 venv 里的解释器，  
效果完全一样，还不会搞错用哪个 Python：

```bash
# 1. 装依赖（只需一次）
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 要跑 pytest 才需要

# 2. 起后端
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 接口文档 http://127.0.0.1:8000/docs
# 健康检查 http://127.0.0.1:8000/api/health
```

```bash
# 3. 前端（另开一个终端）
cd frontend
npm install
npm run dev
# 页面 http://127.0.0.1:5173 （已配置 /api 代理到 8000）
```

**怎么确认自己用的是对的那个 Python**：

```bash
python -c "import sys; print(sys.executable)"
# 应指向 ...\group6\backend\.venv\Scripts\python.exe
# 若指向 D:\python\python.exe 之类，就是没进虚拟环境
```

> 建议用 **Python 3.12 / 3.13**。3.14 上 `pymilvus`、`chromadb` 没有预编译包，  
> 会走源码构建并可能装坏（实测 pymilvus 报 `cannot import name 'rg_pb2'`）。  
> 其中 chromadb 是**可选**依赖（不装会自动降级为内存向量库），装不上不影响运行。

未配置 PostgreSQL / Milvus / 大模型密钥时会自动降级为 SQLite + 内存向量库 + 抽取式生成，

任一外部依赖缺失都不影响启动与演示。

## 三·零、提交前跑一次质量门禁

```bash
python scripts/quality_gate.py                  # 静态检查 + 单元测试
python scripts/quality_gate.py --with-frontend   # 再加前端构建
```

做三件事：ruff（`F,E9`：未定义变量、未使用导入、语法错误）+ pytest（全量）+ 可选前端构建。
**任一项失败就退出码 1**，可以直接挂到 CI 上。规范写在文档里没人执行，写成一条命令才会。

## 三、知识库语料

语料来自 `D:\document\rag_pipeline` 的离线管道产物：**33 篇广东政务办事指南**

（个体工商户设立/变更/注销登记、居住证、城乡居民养老保险、灵活就业社保补贴、

一次性创业资助、房屋所有权首次登记、不动产转移登记、高校毕业生就业创业补贴等）。

默认排除 `GD00_*`（管道生成的"文件索引清单"，关键词磁铁，会把各类问题都吸到同一篇上），

实际入库 **33 篇 / 853 片段**（`GD01~GD32`，其中 `GD12~GD31` 为 2026-09-15 新增）。详见
`backend/README.md` 第六节与根目录《语料扩容与模型切换说明.md》。

### 三条入库路径

**③ 网页工作台自助上传（新增，推荐日常维护用）**

启动服务后打开 http://127.0.0.1:8080 ，左侧切到「工作台」，即可上传
txt / md / pdf / docx（≤10MB）或粘贴文本入库，也能把不再需要的语料移出知识库。
上传的文件落在 `backend/data/uploads/`（已挂载到宿主机，别只存在容器卷里），
内置基准语料 `backend/data/corpus/` 只读，删除后源文件保留、可一键重新导入。
接口与约定见 `backend/README.md` 第 3.1 / 3.2 节。

**① 从语料重新切分 + 现算向量（当前使用的方式）**

```bash
cd backend
python scripts/ingest.py --clear --dir data/corpus
```

每篇先按章节切分再按 500 字 / 100 重叠分块，落 **1024 维**向量
（`qwen3.7-text-embedding-flash`，单请求最多 20 条，`embeddings.py` 已按 10 条一批分片）。

换 Embedding 模型后必须走这条（旧向量维度对不上，没法复用）。

**② 复用已有预计算向量（省 Embedding 调用）**

```bash
python scripts/import_existing_vectors.py --reset
```

源为 `D:\document\rag_pipeline\05_vectorstore\index.json`。

**该源是 2560 维 `qwen3-vl-embedding` 产物**，与当前 1024 维配置不兼容；

脚本会检测维度并直接报错退出（`源 2560 != 配置 VECTOR_DIM 1024`），不会写脏数据。

只有当 `VECTOR_DIM` 与源一致时这条路径才可用。


### 补语料：`GD11_签注居住证`（第 12 篇）

原语料有个缺口：**「居住证签注」没有办事指南**。GD03 / GD03b 里的「签注」

只出现在《居住证暂行条例》式的依据段落（"居住证每年签注一次…到派出所办理签注手续"），

没有该事项的材料 / 流程 / 时限 —— 所以问「居住证到期了怎么续期」时拒答**是正确的**，

不是检索 bug。（顺带一提：GD03 与 GD03b 的正文内容其实都是「申领居住证」，

连 `事项名称` 字段都一样，文件名 `GD03b_...（补换领签注）` 与内容不符，属上游语料问题。）

补语料走的是与原管道一致的口径，保证格式对齐：

```bash
# ① 从广东政务服务网下载办事指南 PDF（wk-pdf 端点，与原语料同源同生成器）
curl -sL -o backend/data/raw_fetch/qz.pdf \
  "https://static.gdzwfw.gov.cn/portal/wk-pdf?code=TE44011350000011905442106041001&template=guide-v2"

# ② 复用原管道的 clean() 清洗（竖排字段还原、去页眉页脚等）
#    再经本项目 clean_text() 过一遍（会去掉"跨域通办"区块）
# ③ 放入 corpus 后单独导入（不必全量重建）
docker-compose exec -T backend \
    python scripts/ingest.py --file /app/data/corpus/GD11_签注居住证_广东政务网.txt
```

结果：**20 片段**，`居住证到期了怎么续期？` 从「必须拒答」转为正常作答

（必备材料 4 条 / 流程 4 步 / 时限 5 个工作日）。

> **新语料带来一个新的清洗规则**：新版办事指南（事项版本 4+）多出「跨域通办」区块，
>
> 会把全省所有市、区、县、镇的名字逐个列出来（本篇约 1350 字）。
>
> 这是典型的**关键词磁铁** —— 问题里只要出现任何地名就会命中这篇文档。
>
> 旧版指南没有这一段，所以只有新抓的语料才会带进来。
>
> `clean_text()` 已加入整块跳过规则（`_SKIP_BLOCK_START` / `_BLOCK_END_MARKERS`），
>
> 并带 400 行兜底上限，避免万一没有结束标志时把整篇文档吃掉。


## 四、生产部署（Docker）

### 一键启动 / 打开 / 停止（Windows 桌面快捷方式）

桌面三个快捷方式，双击即用：

| 快捷方式        | 脚本                | 作用                                                    |
| ----------- | ----------------- | ----------------------------------------------------- |
| **启动政明白**   | `docker-up.bat`   | 起整套 → 等 `/api/health` 就绪 → 自动打开浏览器                     |
| **打开政明白**   | `open-page.bat`   | 先探测服务，在跑才打开 `http://127.0.0.1:8080`；没跑则提示先启动            |
| **停止政明白**   | `docker-down.bat` | 停止并删除容器；命名卷保留，数据库与向量库不丢                               |

`docker-up.bat` 的执行顺序：检测 Docker 引擎 → 定位 compose 命令 → `up -d`
→ 轮询 `/api/health`（最多 180s）→ 就绪后打印健康状态并自动打开浏览器。

> - 「打开政明白」的意义：服务已经在跑时不必再走一遍 `up`，也不会像直接放个网址那样
>   在服务没起时落到"连接被拒绝"的死页 —— 它先 `curl` 探测 `/api/health` 再决定。
> - 两个 Docker 脚本都**优先用 `docker-compose`（带连字符）**：本机没有 compose v2 插件，
>   直接写 `docker compose` 会失败；只有 `docker-compose` 不存在时才回退。
> - 脚本只 `up -d`，**不带 `--build`**。改过后端 / 前端代码要先
>   `docker-compose up -d --build backend frontend`，再双击。
> - 首次部署仍需按下方步骤 ingest 语料，快捷方式只负责起服务。

快捷方式用 `scripts/make_shortcuts.py` 生成（换机器时重跑一次，需 `pip install pywin32`）：

```bash
python scripts/make_shortcuts.py    # 在桌面创建上面三个 .lnk
```

### 两份编排

提供两份编排，**默认用 `docker-compose.yml`**：

| 编排文件                      | 适用场景                                       | 建议 |
| ------------------------- | ------------------------------------------ | -- |
| `docker-compose.yml`      | 完整独立环境：连 PostgreSQL、Milvus(etcd+minio) 一起起 | ✅ **推荐** |
| `docker-compose.host.yml` | 复用宿主机已有的 PostgreSQL / Milvus，只起后端 + 前端 | ⚠️ 见下方已知问题 |

```bash
cp .env.docker.example .env     # 至少填 DASHSCOPE_API_KEY

# A. 完整环境（推荐）
docker-compose up -d --build
docker exec gov-backend python scripts/ingest.py --dir /app/data/corpus

# B. 复用宿主机已有服务（宿主 Milvus 健康时才用）
docker-compose -f docker-compose.host.yml up -d --build
```

> 注意：`docker-compose.yml` 里 backend 对 postgres / milvus 有 `depends_on`
> （`condition: service_healthy`），所以 `up backend frontend` **并不能**只起这两个
> —— 依赖服务会被一起拉起。这恰恰是好事：它保证了后端一定在 Milvus 就绪后才启动。
>
> 反过来说，`docker-compose.host.yml` 没有可依赖的服务，后端会和宿主 Milvus
> **同时**启动。后端若抢跑，会连不上向量库（详见下方已知问题）。

#### ⚠️ `docker-compose.host.yml` 的已知问题（2026-09-14 实测）

宿主 Milvus 若是「**内嵌 etcd + 本地存储**」的 standalone（例如
`milvusdb/milvus:v3.0.0` 挂在 Windows 目录上），会踩两个坑：

1. **重启即崩**：内嵌 etcd 选主竞态，streamingnode 抢跑 `Session.checkIDExist`
   的 Txn → `panic: etcdserver: leader changed`，容器以 **134** 退出，需再
   `docker start` 一次才起得来。
2. **集合无法从磁盘重载**：段文件按 `<localStorage.path>/json_stats/...` 落盘，
   服务端却按 `<root>/files/json_stats/...` 读取 → `invalid local path` →
   集合永久卡在 `Loading(33%)`，检索全部 503。
   **即每次重启 Milvus 后都必须重新 ingest，否则问答全线失效。**

→ 需要稳定环境（尤其演示前）请用 `docker-compose.yml`：
`v2.4.13 + 独立 etcd + MinIO + 命名卷`，实测整套 `down` / `up -d` 后知识库完好。

> 代码侧已加防护（`app/services/milvus_store.py` 的 `LOAD_TIMEOUT`、
> `vectorstore.py` 的 `_connect_with_retry`）：宿主向量库异常时后端**不会**再卡死启动，
> 也不会把故障谎报成"知识库暂无该政策"，而是明确回"检索服务暂时不可用"。

| 服务         | 地址                           | 说明                                         |
| ---------- | ---------------------------- | ------------------------------------------ |
| 前端         | <http://localhost:8080>      | Nginx 静态部署 + `/api` 反向代理                   |
| 后端         | <http://localhost:8000/docs> | FastAPI 接口                                 |
| PostgreSQL | localhost:5432               | 初始化脚本 `backend/sql/schema_postgres.sql`    |
| Milvus     | localhost:**19531**          | 向量库（容器内 19530，宿主侧映射到 19531 以避开本机已有 Milvus） |
| MinIO 控制台  | localhost:9001               | Milvus 的对象存储依赖                             |

> 上表是 `docker-compose.yml`（完整栈）的端口。
>
> 用 `docker-compose.host.yml` 时后端/前端端口相同，但连的是宿主已有服务。

### 部署验证结果（本机实测通过）

以 `docker-compose.yml`（完整栈）为例，构建 + 启动 + 端到端问答全部跑通：

```
docker-compose up -d --build                        # 6 容器全部 healthy
docker exec gov-backend python scripts/ingest.py \
    --dir /app/data/corpus --clear                  # 33 篇 / 853 个片段

$ curl http://127.0.0.1:8000/api/health
{"status":"ok","database":"PostgreSQL","vector_store":"milvus","doc_count":853,
 "llm_provider":"dashscope:deepseek-v4.1-flash","embedding_provider":"dashscope"}

$ curl http://127.0.0.1:8080/            # 前端首页      HTTP 200
$ curl http://127.0.0.1:8080/api/health  # 经 Nginx 反代 HTTP 200
$ curl -X POST http://127.0.0.1:8080/api/chat -d '{...}'
# HTTP 200，返回答案 + 溯源（实测 7~9 条）

# 耐久性：整套 down / up -d 后知识库仍为 853 片段，问答正常
docker-compose down && docker-compose up -d
```

| 镜像                       | 大小                                            |
| ------------------------ | --------------------------------------------- |
| `group6-backend:latest`  | 1.32 GB                                       |
| `group6-frontend:latest` | 102 MB（含 dist 产物 220.89 kB JS / 20.23 kB CSS） |


### 常见问题：命令找不到 / 镜像拉取失败

#### 1. `unknown shorthand flag: 'f' in -f` —— 用错命令了

本机安装的是**独立版 Compose**（`docker-compose` v5.5.1），

**没有** `docker compose` 这个 v2 子插件。写成不带连字符的形式会被

Docker 主 CLI 拿去当全局 flag 解析，于是报上面的错。

```bash
docker compose version      # ❌ docker: unknown command: docker compose
docker-compose --version    # ✅ Docker Compose version v5.5.1
```

本文所有命令统一用 **`docker-compose`（带连字符）**。

#### 2. `dial tcp registry-1.docker.io:443` —— 多数是偶发抖动，先重试

实测本机**可以直连 Docker Hub**（`curl https://registry-1.docker.io/v2/` 返回

`401`，这是 Registry v2 对未认证请求的正常应答，说明链路通）。

`python:3.11-slim` / `node:20-alpine` / `nginx:alpine` 三个基础镜像均已拉取成功。

所以遇到超时先别急着换源，按下面顺序排查：

```bash
# ① 确认链路本身通不通（401/200 都算通，000 才是断）
curl -s -o /dev/null -w "%{http_code}\n" https://registry-1.docker.io/v2/

# ② 排除代理干扰再试一次（本机 shell 里有 http_proxy 时特别有效）
curl -s --noproxy '*' -o /dev/null -w "%{http_code}\n" https://registry-1.docker.io/v2/

# ③ 先把基础镜像单独拉下来，构建时就不用再等网络
docker pull python:3.11-slim
docker pull node:20-alpine
docker pull nginx:alpine

# ④ 再构建
docker-compose -f docker-compose.host.yml build
```

#### 3. 确实拉不动时，配置镜像加速器

Docker Desktop → Settings → Docker Engine（`daemon.json`）：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io"
  ]
}
```

> 只留 **`docker.m.daocloud.io`** 一个。实测它在国内可用（同样返回 401）；
>
> 而常见的 `hub-mirror.c.163.com`、`mirror.ccs.tencentyun.com` 现在返回 `000`，
>
> 已经失效 —— 配了反而会拖慢每次拉取（Docker 会逐个源串行重试）。
>
> 改完点 Apply & Restart 生效。

#### 4. 构建期软件源（已内置，无需手工改）

| 阶段            | 源                                              |
| ------------- | ---------------------------------------------- |
| `pip install` | `PIP_INDEX_URL` 已在 Dockerfile 里写死清华源           |
| `npm install` | 已用 `--registry=https://registry.npmmirror.com` |
| `apt-get`     | 走 Debian 官方源（仅装 `gcc`，包很小）                     |


### 完整栈（`docker-compose.yml`）专项排坑

自带 PG + Milvus 的这份编排，实测踩到三个"不试就发现不了"的坑，均已修复：

| # | 坑                    | 现象                                                                                                                                                  | 修法                                                                |
| - | -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1 | **MinIO 镜像已下架**      | `minio/minio:RELEASE.2023-03-20T20-16-18Z` 报 `pull access denied, repository does not exist`。Docker Hub 上 `minio/minio` **整个仓库都没了，连 `latest` 都拉不到** | 改用 `quay.io/minio/minio:RELEASE.2023-03-20T20-16-18Z`（实测可拉）       |
| 2 | **19530 端口冲突**       | 本机通常已跑着一套 Milvus（占 19530/2379/9091），`19530:19530` 会 `address already in use`                                                                        | 宿主侧改映射 `19531:19530`。容器内仍是 19530，backend 走服务名 `milvus:19530` 不受影响 |
| 3 | **healthcheck 工具缺失** | 想当然写成 `mc ready local`，实测该镜像**有 `curl`、没有 `mc`**                                                                                                    | 保持 `curl -f http://localhost:9000/minio/health/live`              |

> 顺带确认 `milvusdb/milvus:v2.4.13` 内有 `curl`，其 `9091/healthz` 探针可用。

**完整栈实测结果（6 个容器全 healthy）**：

```
gov-postgres       postgres:16                     healthy   5432
gov-milvus-etcd    quay.io/coreos/etcd:v3.5.5      healthy
gov-milvus-minio   quay.io/minio/minio:...         healthy   9000-9001
gov-milvus         milvusdb/milvus:v2.4.13         healthy   19531->19530
gov-backend        group6-backend                  healthy   8000
gov-frontend       group6-frontend                 up        8080
```

- 容器内 PG 自动建表：`session` / `chat_history` / `doc_meta` 三张
- 后端连的是**容器内**的 postgres + milvus（不是宿主那套），health 返回 `doc_count: 0`
- 空库问答 **HTTP 200 / 0.025s** 优雅降级（返回"知识库暂无该业务相关政策"），不 500 不挂起
- 容器内导入链路验证：`python scripts/ingest.py --file ...` → 1 篇文档 11 片段，

  `doc_count` 由 0 变 11 ✅

**语料已纳入仓库**：33 篇广东政务指南（约 250 KB）放在 `backend/data/corpus/`，

以只读方式挂载到容器 `/app/data/corpus`，`DOCS_DIR` 也指向它 —— 完整栈可直接导入，

不再依赖仓库外的 `D:\document\rag_pipeline\`。

镜像里另保留了 `backend/data/docs/` 的 6 篇 2KB 示例文档，供离线开发/测试用。

**元文档不要进知识库**：`GD00_广东省政务办事指南索引清单.txt` 已移到

`backend/data/corpus_meta/`（该目录不参与导入）。它记录的是"收录了哪些 PDF、来源、页数"

这类**语料来源信息**，不是政策内容，还带 `D:\document` 这类本地路径。

更要命的是它罗列了全部事项名称，是典型"关键词磁铁"——实测问"灵活就业社保补贴需要什么材料"

时它会以 0.82 的分数混进溯源。移出后 `corpus/` 正好 11 篇（后补入 GD11 签注居住证，现为 12 篇）。

**首次导入 / 换模型后重建（别在启动时自动跑）**：

```bash
# 完整栈
docker-compose -f docker-compose.yml exec -T backend \
    python scripts/ingest.py --clear --dir /app/data/corpus

# 复用宿主 PG/Milvus
docker-compose -f docker-compose.host.yml exec -T backend \
    python scripts/ingest.py --clear --dir /app/data/corpus
```

> **两份编排都必须挂载语料**（`./backend/data/corpus:/app/data/corpus:ro` + `DOCS_DIR`）。
>
> `docker-compose.host.yml` 早期漏了这段，容器里没有 `/app/data/corpus`，
>
> 上面这条命令会「跑通但不导入任何东西」—— 不报错，只是知识库永远是空的。
>
> `tests/test_env_sync.py::test_both_compose_files_mount_corpus` 已把这点钉死。

> `AUTO_INGEST_ON_STARTUP` 保持 `false`。800+ 个片段的 embedding 要跑约 7 分钟，
>
> 而导入写在 lifespan 里会**阻塞 uvicorn**，期间 healthcheck 连续失败会把容器标成 unhealthy。
>
> 实测：**33 篇 → 853 片段**（1024 维），约 7 分钟。

> 命令里的 `-T` 是禁用 TTY，便于脚本/管道调用；在交互终端里加不加都行。
>
> 换行符 `\` 是 bash 写法，CMD 请写成一行，PowerShell 用反引号 `` ` ``。


### ⚠️ 修复：`clean_text` 曾吃掉 28.7% 的正文

完整栈首次导入只得到 382 片段，而原 RAG 管道同样语料是 570 —— 少了 33%。定位后确认是

`app/utils/text.py` 的清洗逻辑过激：

| 问题           | 原因                                       | 后果                                  |
| ------------ | ---------------------------------------- | ----------------------------------- |
| 页眉正则匹配任意纯数字行 | `第?` / `页?` 都写成可选，正则退化成 `^\s*[0-9]+\s*$` | **事项业务编码**（如 `5442106041002`）被当页眉删除 |
| 短行去重范围过大     | 判据是"全文出现过的短行"，不是"紧邻上一行"                  | 政务表单里合法重复的 `否` / `无` 被去重            |

修复：页码正则改为必须出现「页」或「N / 共 M」；去重改为只针对**连续重复行**。

> 📌 以下数字是**当时的测量记录**（语料为 11 篇时），用于说明修复效果，
> 不代表当前规模。当前语料已扩到 33 篇 / 853 片段（见「补语料」一节）。

| 指标                | 修复前               | 修复后         |
| ----------------- | ----------------- | ----------- |
| `clean_text` 字符损失 | 59,603（**28.7%**） | 1,421（0.7%） |
| 片段数（当时 11 篇）      | 382               | **534**     |

已验证 `chunk_text` 本身无损（切分后总和 ≈ 清洗后正文 × 500/400，正好是重叠系数）。

修复后 58 项测试仍全绿（当时规模）。

> 两套分块口径不同是正常的：本仓库原生导入得 527 片段（当时 11 篇），原 `rag_pipeline` 的
>
> `RecursiveCharacterTextSplitter` 得 562。二者 `chunk_size=500 / overlap=100` 一致，
>
> 差异来自 NFKC 归一化与空行处理。

**宿主库（当时 562 片段）无需重建 —— 已验证无损失**：

```bash
docker-compose -f docker-compose.host.yml exec backend python -c "...query gov_docs..."
```

| 检查项                                                      | 结果                                        |
| -------------------------------------------------------- | ----------------------------------------- |
| 片段数 / 文档数（当时）                                            | 562 / 11                                  |
| 业务编码 `5442106041002`、`442106041002`、`TE4401135000001170` | 全部**命中**                                  |
| 片段总字符 vs 源文                                              | 244,407 / 202,219 = 1.21 倍，落在重叠系数 1.25 附近 |

宿主库走的是 `rag_pipeline` 预切分产物，没有经过这个有 bug 的 `clean_text`，所以内容完好。

**回归评测**：`python scripts/eval_rag.py` → **29 / 29 通过**，总耗时 216s

（在 `docker-compose.host.yml` + 宿主 Milvus 上实测，且已启用"答案不得拒答"检查）。

| 分组                         | 用例 | 说明             |
| -------------------------- | -- | -------------- |
| 域内：命中正确文档 + 给出材料清单         | 12 | 还要求**不得拒答**    |
| 挑战·易混淆事项（设立/变更/注销）首选文档必须正确 | 3  |                |
| 挑战·数值精确（承诺办结时限）            | 4  |                |
| 挑战·只有法规引用、没有办事指南（居住证签注）    | 1  | 语料里只有依据条文，必须拒答 |
| 挑战·领域内未收录（护照/公租房/车牌/港澳通行证） | 4  | 必须拒答           |
| 域外：必须拒答，不得编造               | 5  |                |

> **评测本身也修过一个盲区**：早期「域内」「易混淆」两组只检查
>
> 「命中的文档对不对 + 材料条数够不够」，从不看答案正文。
>
> 于是「检索命中、但模型返回拒答」这种自相矛盾的响应会被判成**通过**
>
> —— 实测「居住证到期了怎么续期」就是这样混过去的。
>
> 现在会检查答案是否以拒答话术开头。

单轮耗时：命中 8~15s，被闸门拦截 1.2s（不进生成，直接返回）。


### 检索质量的六个坑（已修复）

1. **文档标题撞名**：GD03 / GD03b 的正文首行都是「申领居住证」（PDF 页眉串了），

   库里两篇同名，导致「第一次申领」和「到期续期」根本无法区分。

   → 改为优先从**文件名**取标题（`_title_from_filename`），12 篇全部唯一。
2. **材料清单章节取错片段**：该章节动辄上万字，分数最高的往往是「填报须知」噪声段

   （含 原件/复印件 字样所以像材料表，但解析不出任何条目），结果必备材料为 0 条。

   → 同章节多片段时，材料类章节改为**优先取真正能解析出材料行的片段**。
3. **结构化字段从不补全**：`enrich_sections` 的触发词只有材料类意图词，

   问「承诺多少个工作日办结」时它根本不执行，Top-4 全是审批信息却没有

   「承诺办结时限」那一段。→ 触发词扩展为 `STRUCTURED_INTENT_KEYS`，候选池同步放大。
4. **口语够不到闸门**：群众说「改名字」，语料写「变更登记」，字面零重叠，

   向量 0.760 / 关键词 9.4 两个通道都过不了闸，被当成域外拒答。

   → `expand_query` 增加「改名/更名 → 变更登记」。
5. **向量库按章节去重，长章节只能召回一段**（Milvus 上才暴露）：

   `search()` 最后按 `(doc_id, section)` 去重，一个章节只留一条。

   「材料清单」被切成 20~37 段，去重后留下的恰是「填报须知」噪声段，

   一条材料都解析不出来 —— 表现为「个体工商户设立登记需要哪些材料」答 0 条。

   在内存库上碰巧蒙对，换成 Milvus 就稳定复现。

   → 新增 `fetch_section()` 绕开去重，`_complete_material_chunks()` 在合并**之后**

   补齐同章节的其他材料表片段（只补不换，避免越修越差）。

   实测该问题让 GD01 从 0 条变 4 条、GD08 从 3 条变 6 条。
6. **文档级排序打平，靠顺序决定主文档**：`_rerank` 先按「文档最高分」排，

   打平时退化成看谁先出现。「办理个体工商户营业执照怎么办？」里，

   个体工商户注销登记与设立登记最高分都是 0.821，注销靠顺序胜出 →

   上下文全是注销内容 → 模型判定「资料没讲营业执照怎么办」，**直接拒答**。

   → 引入「佐证分」（该文档召回片段原始分之和，取前 3）做打平裁决：

   设立登记有两段佐证（0.821 + 0.469）压过注销的单段，主文档纠正过来。

   实测该问题从「拒答」恢复为正确回答「需申请办理个体工商户设立登记」。

> 上面第 5 条还带来一个教训：**闸门阈值必须在生产用的向量库上标定**。
>
> Milvus 走 ANN 近似检索，top-K 与暴力检索会差一两条，导致「域外最高关键词分」
>
> 从 30.17 漂到 31.55。在内存库上标出的 30.7 拿到 Milvus 用，就会有域外问题
>
> 从关键词通道漏进来。现在 `calibrate_gate.py` 会打印本次标定针对哪个向量库。

### 部署相关的两个坑（已修复）

1. **Nginx 读超时**：`proxy_read_timeout` 原为 120s，而推理模型单轮最长 300s，

   Nginx 会先掐断导致前端只看到 504 → 现改为 330s。
2. **闸门阈值未随镜像下发**：`config.py` 里的默认值仍是 1024 维时代的

   `0.18 / 7.0`，而实际使用的多模态向量需要另一套阈值。

   两份编排都已显式注入 `VECTOR_MIN_SCORE` / `KEYWORD_MIN_SCORE`。

   **换 Embedding 模型时必须重新标定**，见下面「五、切换模型」。

## 五、切换模型（可选）

编辑 `backend/.env`：

```bash
# tongyi-embedding-vision-flash（多模态，768 维，必须走原生端点）
EMBEDDING_PROVIDER=dashscope_native
DASHSCOPE_EMBED_MODEL=tongyi-embedding-vision-flash
VECTOR_DIM=768
# 或 qwen3-vl-embedding（多模态，2560 维，同一端点）
# DASHSCOPE_EMBED_MODEL=qwen3-vl-embedding
# VECTOR_DIM=2560
# 或 text-embedding-v3（1024 维，OpenAI 兼容模式）
# EMBEDDING_PROVIDER=dashscope
# VECTOR_DIM=1024

LLM_PROVIDER=dashscope     # deepseek-v4.1-flash；或 extractive（离线抽取式兜底）
DASHSCOPE_MODEL=deepseek-v4.1-flash
DASHSCOPE_API_KEY=sk-xxxxxxxx

# 思考模型专用：deepseek-v4.1-flash 原生思考链，服务端恒开（传 false 也关不掉）
LLM_TIMEOUT=300           # 单次调用超时（秒）
LLM_ENABLE_THINKING=true  # 显式保持思考模式（extra_body={"enable_thinking": True}）
LLM_MAX_TOKENS=4096       # 防止长答案被截断成半个 JSON；思考模式下代码自动抬到 8192
LLM_THINKING_BUDGET=0     # 思考 token 上限，仅 qwen 系支持（deepseek 会忽略该参数）
```

`PIPELINE=langchain` 可切换为 LangChain 实现（Loader / TextSplitter / Retriever / LCEL 链），

`PIPELINE=native` 为自研实现，两者检索与生成结果一致。


### 换模型后必须重新标定相关性闸门

相关性闸门用的是**绝对分**（`VECTOR_MIN_SCORE` 向量余弦 / `KEYWORD_MIN_SCORE` BM25），

不是排序分。绝对分的量纲完全由 Embedding 模型决定，所以**换模型不重新标定必出问题**：

| 情况   | 表现                  |
| ---- | ------------------- |
| 阈值偏高 | 域内问题被误杀成「暂无该业务相关政策」 |
| 阈值偏低 | 域外问题穿过闸门，大模型开始编造    |

标定脚本会跑一批域内 / 域外问题，打印分数分布并给出推荐切点：

```bash
cd backend
python scripts/calibrate_gate.py           # 打印分布 + 推荐值
python scripts/calibrate_gate.py --write   # 写回 .env
```

闸门以**向量语义为主判据**：`vec ≥ VECTOR_MIN_SCORE` 通过；否则要求
`关键词 ≥ KEYWORD_MIN_SCORE` **且** `融合分 ≥ FUSED_MIN_SCORE` 两项同时成立。
改判据的原因：口语化泛问（"我想开个小店，要办啥"）与政务术语零重叠，BM25 只有
单二元组噪声，旧口径会把它整体判成"域外"拒答。

实测结果（`qwen3.7-text-embedding-flash` / **1024 维** / **Milvus** / 33 篇语料 853 片段，纯向量排序后）：

| 通道       | 标准问法（12 条）    | 口语化泛问（21 条）   | 域外（6 条）      | 标定阈值                       |
| -------- | ------------ | -------------- | ------------- | -------------------------- |
| 向量余弦     | 0.709 ~ 0.968 | 0.428 ~ 0.836 | 0.331 ~ 0.353 | `VECTOR_MIN_SCORE=0.45`    |
| BM25 关键词 | 0 ~ 74.0     | 0 ~ 42.3       | 0 ~ 10.2      | `KEYWORD_MIN_SCORE=44.3` + `FUSED_MIN_SCORE=0.62` |

> 2026-09-15 补入 GD32《社会保障卡申领》后复测：域外最高分 0.353、口语化最低 0.428，
> 与 0.45 仍有安全间隔，因此**阈值未调整**。

> 换过一次 Embedding 就足以让阈值作废：同一套问法在 768 维
> `tongyi-embedding-vision-flash` 下是 0.71~0.93 / 域外 0.58~0.72（阈值取 0.73），
> 换到 1024 维后整体下移到 0.42~0.97 / 域外 0.33~0.36（阈值取 0.45）。

> 标定脚本 `calibrate_gate.py` 只覆盖"标准问法"，**覆盖不到口语化泛问**，
> 而后者恰恰是向量分最低的一档。标定后务必再跑
> `docker exec gov-backend python scripts/probe_gate.py` 复核口语化样本。
> 宿主机端到端冒烟：`python scripts/qa_smoke.py`（打 8080）。

`scripts/check_env.py` 会校验「模型实际返回维度 == `VECTOR_DIM`」。

> 标定必须在**生产用的那个向量库**上做：同一份数据，内存库（暴力检索）和
>
> Milvus（ANN 近似）的 top-K 会差一两条，边界值随之漂移。

> 另注：`VECTOR_DIM` 写错时，Milvus 会**直接删集合重建**，本地 JSON 向量库
>
> 现在会检测维度不一致并丢弃重建（旧文件留档为 `.bak`）。
>
> 早期版本没有这个校验，表现是「换完模型知识库看着是满的，但检索分数全错」。

### 两份 `.env` 的分工（容易踩）

| 文件             | 被谁读取                     | 作用          |
| -------------- | ------------------------ | ----------- |
| `backend/.env` | 应用运行时（pydantic-settings） | **真正生效的配置** |
| `.env`（仓库根）    | `docker-compose` 变量替换    | 只影响容器化部署    |

两者必须同步改。只改根目录那份，本机直接跑 `uvicorn` 时完全不会生效。

### ⚠️ 换 Key 之后容器里还是旧 Key？（最隐蔽的一个坑）

**`docker-compose` 的变量替换优先读「shell 环境变量」，其次才读 `.env` 文件。**
只要当前环境里存在同名变量，`${DASHSCOPE_API_KEY:-}` 就会取到**环境变量的值**，
你改 `.env` 根本不会生效。

这个"环境变量"有三种来源，**第三种最阴**——重启电脑后它依然存在：

| 来源 | 作用域 | 重启后是否还在 |
|---|---|---|
| `export VAR=x` | 仅当前终端 | 否 |
| 用户级环境变量（`HKCU\Environment`） | 当前用户所有终端 | **是** |
| 系统级环境变量（`HKLM\...\Session Manager\Environment`） | 整机所有进程 | **是** |

2026-09-15 实测踩到第三种：本机 **Machine 级残留了一个失效的旧 `DASHSCOPE_API_KEY`**
（117 位）。重启电脑后每次 `up -d` 都被它劫持，表现为**问什么都答「知识库暂无该业务政策」**
——根因是向量化 401 → 检索失败 → 无命中，**并不是真的没有数据**。

```bash
# 查：注册表里的持久环境变量（reg.exe 可能被安全策略拦截，用 python 读更稳）
python -c "
import winreg
for hive, path, label in [
    (winreg.HKEY_CURRENT_USER, 'Environment', '用户级'),
    (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', '系统级'),
]:
    try:
        v = winreg.QueryValueEx(winreg.OpenKey(hive, path), 'DASHSCOPE_API_KEY')[0]
        print(label, 'len=', len(v), 'tail=', v[-6:])
    except FileNotFoundError:
        print(label, '未设置')
"
# 和 .env 里的比：长度 / 尾 6 位不一致，就是被劫持了
```

**根治：删掉那个环境变量**（系统级需管理员 PowerShell）：

```powershell
[Environment]::SetEnvironmentVariable('DASHSCOPE_API_KEY', $null, 'Machine')
```

**加固（已实施，2026-09-15）**：`docker-compose.yml` 的 `backend` 服务改用
`env_file: [.env]`，密钥类变量不再写成 `${VAR}` 插值。`env_file` 是直接读文件注入容器、
**不经过 shell 插值**，因此无论环境里有什么同名变量，`.env` 始终说了算。
（已实测：故意在命令行前置一个假 Key 再 `--force-recreate`，容器内仍是 `.env` 的值。）

> 通用规则：`${VAR}` 写法的优先级是 **shell / 持久环境变量 > `.env` 文件**。
> 凡是"改了 `.env` 不生效"的现象，先怀疑这个。

**改动 `.env` 后容器必须重建才会生效**（`--force-recreate`），
因为环境变量是在容器创建时注入的，只 `restart` 不会重新读。

**怎么确认容器里到底是哪个 Key**（不要全量打印，看长度和头尾即可）：

```bash
docker exec gov-backend python -c "
import os, hashlib
k = os.environ.get('DASHSCOPE_API_KEY','')
print('len=', len(k), 'sha8=', hashlib.sha256(k.encode()).hexdigest()[:8], 'tail=', k[-6:])
"
# 和 .env 里的比对
grep -E '^DASHSCOPE_API_KEY' .env | cut -d= -f2- | awk '{print length($0), substr($0,1,12), substr($0,length($0)-5)}'
```

#### ⚠️ 同一个 401 症状的第二种成因：`.env` 是 CRLF，`\r` 被当成 Key 的一部分

2026-09-14 实测踩到：**Key 完全有效，却被 DashScope 判 `InvalidApiKey`**。

根因是 `.env` / `backend/.env` 用 **CRLF** 换行，密钥值尾部多了一个 `\r`
（长度 117 而不是 116）。HTTP 头里混入 `\r` 后，Authorization 的值被污染，
服务端只能判无效。

```bash
# 查换行符：CRLF 会显示 \r\n
file .env backend/.env

# 修：统一转成 LF（去掉所有 \r）
python -c "
import io
for p in ['.env','backend/.env']:
    raw = io.open(p,'rb').read()
    io.open(p,'wb').write(raw.replace(b'\r\n', b'\n'))
    print(p, 'CRLF ->', raw.count(b'\r\n'), '处已转 LF')
"
```

> **教训**：报 401 不等于 Key 过期。先用上面的 `len()` 比一下长度——
> 差 1 位基本就是 `\r`；差得多才是 Key 不对。

> 顺带一提：`.env.docker.example` 是模板文件，**不要在里面放真实 Key**——
> 这个项目里它虽然未被 git 跟踪，但模板文件的惯例是留空或占位符。


## 六、验收清单

- [x] 12 篇广东政务文档语料入库（580 片段 / 768 维向量）
- [x] 域内问题命中正确文档，输出必备 / 可选材料、办理流程、部门、时限、收费
- [x] 答案可溯源（命中文档、章节、相似度评分）
- [x] 域外问题返回"知识库暂无该业务相关政策"，拒绝编造（5/5 全部拦截）
- [x] 多轮会话：历史写入 PostgreSQL、上下文裁剪、会话切换与历史回放
- [x] 后端不可用时前端自动降级为本地演示数据（`VITE_ENABLE_MOCK`）
- [x] 测试 120 项：材料抽取 / 重排 / 文本工具 / 闸门标定 / 向量库维度防护 / 配置一致性（112 项纯离线）+ 接口契约（8 项，桩替换 RAG）

回归测试：

```bash
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 仅首次：pytest 不在 requirements.txt 里
.venv\Scripts\python.exe -m pytest                                # 全部测试（120 项）
.venv\Scripts\python.exe -m pytest -m "not integration"           # 仅离线单元测试（112 项，不依赖外部服务）
.venv\Scripts\python.exe scripts/eval_rag.py                      # RAG 质量评测：29 例
.venv\Scripts\python.exe scripts/calibrate_gate.py                # 相关性闸门阈值标定（换 Embedding 模型后必跑）
.venv\Scripts\python.exe scripts/test_api.py                      # 接口冒烟：三接口 + 参数校验
.venv\Scripts\python.exe scripts/check_env.py                     # 依赖自检（可加 --skip-llm）
```

> 若已 `activate` 进虚拟环境，把 `.venv\Scripts\python.exe ` 换成 `python ` 即可。  
> macOS / Linux 用 `.venv/bin/python`。  
> `scripts/test_api.py`、`eval_rag.py`、`check_env.py` 需要后端已在 8000 端口运行。

| 命令             | 是否需要后端在跑 | 是否需要外部服务                       |
| -------------- | -------- | ------------------------------ |
| `pytest`       | 否        | 否（接口测试用桩替换 RAG）                |
| `check_env.py` | 否        | 是（探活 PostgreSQL / Milvus / 模型） |
| `test_api.py`  | **是**    | 是                              |
| `eval_rag.py`  | **是**    | 是（会真实调用大模型，约 4 分钟）             |

单元测试覆盖最容易回归的几块逻辑（`backend/tests/`）：

| 测试文件                      | 项数 | 覆盖内容                                                                                        |
| ------------------------- | -- | ------------------------------------------------------------------------------------------- |
| `test_material.py`        | 24 | PDF 材料表行结构还原、噪声判定、章节门控（PDF 把单元格拆成多行，逻辑最脆）                                                   |
| `test_text_utils.py`      | 27 | 输入过滤（控制字符 / URL / 刷屏字符）、清洗保中文标点、分块、章节切分、**清洗不得误删事项编码**                                      |
| `test_calibrate_gate.py`  | 15 | 闸门阈值标定：可分组 / 重叠 / 平移不变性，**「或」语义下的联合标定**                                                     |
| `test_rerank.py`          | 22 | 意图感知重排：章节加权、依据降权、查询扩展、**文档顺序不得被重排改变**、同章节片段择优、**打平时按佐证分裁决**                                 |
| `test_env_sync.py`        | 12 | 配置文件一致性：`backend/.env` / 根 `.env` / `.env.docker.example` / 两份编排的 `VECTOR_DIM`、模型名、闸门阈值必须一致 |
| `test_api_contract.py`    | 8  | 三接口契约与参数校验（桩替换 RAG）                                                                         |
| `test_vectorstore_dim.py` | 5  | 本地向量库**维度漂移**防护：换模型后不得静默沿用旧维度向量                                                             |
| `test_api_contract.py`    | 8  | 接口契约（需 PG/Milvus，不可用自动跳过）：健康检查、空问题/超长问题拒答、会话自动补建、历史持久化                                      |

`test_api_contract.py` 用 TestClient 跑真实 FastAPI 应用，但把 RAG 换成桩，**不调用大模型**；

会真实写入 `session`/`chat_history`，测试结束自行清理。
