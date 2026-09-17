# CI/CD 配置说明

> 适用版本：2026-09-17。对应文件：`.github/workflows/ci.yml`、`.github/workflows/cd.yml`、
> `docker-compose.deploy.yml`。

## 一、架构与流水线对应关系

| 组件 | 技术 | CI 环节 | 产物 |
|---|---|---|---|
| 后端 | FastAPI + SQLAlchemy + pymilvus，Python 3.11 镜像 | `backend-test` | 测试报告 |
| 前端 | Vue 3 + Vite 5，Node 20 构建、Nginx 运行 | `frontend-build` | `frontend/dist` 产物、镜像 |
| 数据 | PostgreSQL 16 | `smoke` 起全栈验证 | — |
| 向量库 | Milvus 2.4.13（+ etcd + MinIO） | `smoke` 起全栈验证 | — |
| 交付 | GHCR 镜像 + SSH 滚动更新 | `cd.yml` | `ghcr.io/<owner>/<repo>/backend`、`/frontend` |

流水线总览：

```
push / PR ──► CI ──► backend-test (py3.11/3.12)
              │  └─► frontend-build (npm ci + vite build)
              └─► docker-build (compose 校验 + 双镜像构建)
                     └─► smoke（仅默认分支 push）起全栈 + /api/health 断言

main / tag ─► CD ──► build-and-push → ghcr.io
                 └─► deploy（SSH：scp 编排文件 → pull → up -d → 健康检查）
```

## 二、CI 关键设计（为什么这么写）

1. **测试不依赖外部服务。** `DB_HOST` 留空时应用自动降级到 SQLite + 内存向量库，
   `tests/test_api_contract.py` 里的 integration 用例会自行 skip。CI 3~5 分钟跑完，
   不会因为 Milvus 抖动误报红灯。
2. **复用 `scripts/quality_gate.py`。** CI 不另写一套 ruff/pytest 命令，直接调仓库里
   已有的门禁脚本（ruff `--select F,E9` + pytest），本地与 CI 完全同命令。
3. **`.env` 现场生成。** `backend/.env` 与根目录 `.env` 含密钥、不入库，
   CI 里 `cp` 对应的 `.example` 生成。这同时反向验证了 `tests/test_env_sync.py` 钉死的
   「7 个关键配置在 5 处必须一致」。
4. **`.gitignore` 已修一处坑：** 原规则 `.env.*` 会把 `backend/.env.example` 一起忽略，
   导致 CI 里 `cp` 失败。已补 `!**/.env.example`。
5. **冒烟只验依赖不验知识库。** 断言 `status=ok` 且 `vector_store=milvus` 且
   `database=PostgreSQL` —— 只验 HTTP 200 的话，向量库降级成内存库也会「通过」。
   `AUTO_INGEST_ON_STARTUP=false`，不重灌（灌一次约 6 分钟，会阻塞 uvicorn 起不来）。

## 三、首次启用

### 1. 本机已完成的部分

```bash
git init -b main          ✅ 已执行
git add -A                ✅ 已执行（148 个文件，已确认 .env / .venv / node_modules 均未入库）
git commit                ✅ 已执行（4b77524）
git remote add origin …   ⬜ 等你建好 GitHub 仓库后再执行
git push -u origin main   ⬜ 同上
```

顺带补了两个文件：

- `.gitattributes` —— 统一 LF。本项目踩过两次 CRLF 的坑：`.sh` 带 `\r` 直接
  `bad interpreter`；`.env` 值尾部混进 `\r` 会让 API Key 多一位 → DashScope 401。
- `.gitignore` 追加 `frontend/vite.config.js.timestamp-*.mjs`（Vite 临时文件）。

### 2. 你需要在 GitHub 网页上做的（唯一一次）

1. 打开 <https://github.com/new>
2. Repository name 随便填（如 `govrag`）
3. Visibility：选 **Private**（GHCR 镜像继承仓库可见性；语料与配置模板虽不含密钥，私密更省心）
4. **不要勾选** Add a README / .gitignore / License —— 必须是个**空仓库**，否则 push 会被拒
5. 点 Create repository

创建完成后，页面会显示仓库地址，复制它（形如 `https://github.com/<你的用户名>/govrag.git`）。

### 3. 回到本机执行两条命令

```bash
cd /d/group6
git remote add origin https://github.com/<你的用户名>/govrag.git
git push -u origin main
```

> 本机装了 Git Credential Manager（`credential.helper=manager`），首次 push 会弹出
> GitHub 登录窗口，用浏览器授权即可，**不需要自己生成 Token 或 SSH key**。
> 想用 SSH 也行：把地址换成 `git@github.com:<用户名>/govrag.git`，前提是本机
> `~/.ssh` 里已有密钥并已添加到 GitHub（当前本机 `~/.ssh` 为空，HTTPS 更省事）。

推送后 Actions 自动触发。GHCR 推送用的是内置 `GITHUB_TOKEN`，**无需额外配置**。
第一次 CI 大约 8~12 分钟（依赖安装 + 两个镜像构建 + 全栈冒烟），之后有缓存会快很多。

## 四、部署配置（可选，配了才会部署）

未配置 `DEPLOY_HOST` 时，`cd.yml` 的 deploy 任务**自动跳过**，只推镜像。

### 1. 仓库 Secrets（Settings → Secrets and variables → Actions）

| Secret | 必填 | 说明 |
|---|---|---|
| `DEPLOY_HOST` | ✅ | 服务器 IP / 域名 |
| `DEPLOY_USER` | ✅ | SSH 用户（需有 docker 权限，建议加入 `docker` 组） |
| `DEPLOY_SSH_KEY` | ✅ | SSH 私钥全文（`-----BEGIN ... PRIVATE KEY-----`） |
| `DEPLOY_PATH` | ✅ | 项目目录，如 `/opt/govrag` |
| `DEPLOY_PORT` | ❌ | 默认 22 |
| `GHCR_PAT` | ❌ | 拉私有镜像的 PAT（`read:packages`）。不配则回退 `GITHUB_TOKEN` |

建议给 `production` 环境加上 Required reviewers（Settings → Environments），
避免每次 push 都直接上生产。

### 2. 服务器准备

```bash
sudo mkdir -p /opt/govrag && sudo chown $USER /opt/govrag
# 首次：从仓库取一份示例配置，填入真实密钥
cp .env.docker.example .env
vi .env        # 必填 DASHSCOPE_API_KEY；生产环境务必改掉 POSTGRES_PASSWORD 弱口令
```

> `.env` 只存在于服务器，不入库、不随 scp 传输 —— CD 只会推 `docker-compose.yml`
> 与 `docker-compose.deploy.yml` 两个文件。
> 若 `.env` 不存在，deploy 会**直接失败并提示**，不会带着空密钥把服务拉起来。

### 3. 首次灌知识库

镜像里的语料是 `backend/data/corpus`（33 篇，以只读方式挂载），但向量库是空的：

```bash
cd /opt/govrag
BACKEND_IMAGE=ghcr.io/<owner>/<repo>/backend:latest \
FRONTEND_IMAGE=ghcr.io/<owner>/<repo>/frontend:latest \
docker compose -f docker-compose.yml -f docker-compose.deploy.yml up -d
docker compose exec backend python scripts/ingest.py --dir /app/data/corpus --clear
```

之后如需重建，可在 Actions 手动触发 CD 时勾选 `ingest`。

## 五、常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| `backend/.env.example` 找不到 | `.gitignore` 把示例文件挡了 | 已修；本地若此前被忽略过需 `git add -f` 一次 |
| `test_env_sync` 报「缺少 KEY」 | 换模型只改了部分配置 | 7 个键 × 5 处必须同步：`backend/.env`、`backend/.env.example`、`.env`、`.env.docker.example`、`docker-compose.yml`、`docker-compose.host.yml` |
| 冒烟卡在 Milvus | runner 内存/时间不够 | 调大 `smoke.timeout-minutes` 或确认 `--wait-timeout` |
| deploy 跳过 | 未配 `DEPLOY_HOST` | 按第四节配置 Secrets |
| 部署后答「知识库暂无…」 | 向量库空或 DashScope 401 | `docker compose logs gov-backend \| grep 大模型调用失败`；401 先查 key 是否被 CRLF 污染 |
| 上传 >1MB 报 413 | Nginx 网关拦截 | `nginx.conf` 已设 `client_max_body_size 20m` |

## 六、镜像标签规则

由 `docker/metadata-action` 生成：

- 默认分支 push → `latest` + `main` + `sha-<完整 commit>`
- tag push（`v1.2.3`）→ `1.2.3` + `1.2` + `v1.2.3` + `sha-...`；CD 部署用 tag 名
- 回滚：手动触发 CD，或直接 `IMAGE_TAG=sha-xxxx docker compose ... up -d`
