"""FastAPI 应用入口：跨域、路由注册、异常处理、启动初始化。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .database import ACTIVE_DB_TYPE, init_db
from .routers import chat, corpus, history, session
from .schemas import HealthResponse

_DB_LABEL = {"postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动：建表 + 知识库自动初始化。"""
    init_db()
    print(f"[init] Database = {_DB_LABEL.get(ACTIVE_DB_TYPE, ACTIVE_DB_TYPE)}")

    from .services.ingest import ingest_dir
    from .services.vectorstore import get_vector_store

    store = get_vector_store()
    if settings.AUTO_INGEST_ON_STARTUP and store.count() == 0:
        r = ingest_dir()
        print(f"[init] 知识库初始化完成：文档 {r['total']} 篇 / 文本块 {r['chunks']} 个")
    else:
        print(f"[init] 知识库已有 {store.count()} 个文本块，跳过导入")

    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="后端服务层：提供会话管理、政务 RAG 问答与办事材料清单生成接口",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------- 跨域 ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- 路由 ----------------
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(history.router)
app.include_router(corpus.router)


# ---------------- 异常捕获 ----------------
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """参数校验失败：返回可读的错误提示。"""
    msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:]) or 'body'}: {e['msg']}" for e in exc.errors()[:3])
    return JSONResponse(status_code=400, content={"detail": f"请求参数不合法（{msg}）"})


@app.exception_handler(Exception)
async def global_handler(request: Request, exc: Exception):
    """兜底异常处理：避免堆栈暴露给前端。"""
    return JSONResponse(
        status_code=500,
        content={"detail": "服务内部异常，请稍后重试或咨询线下政务窗口"},
    )


# ---------------- 健康检查 ----------------
@app.get("/", tags=["系统"])
def root():
    return {
        "name": settings.APP_NAME,
        "docs": "/docs",
        "health": "/api/health",
        "apis": [
            "POST /api/session/create",
            "POST /api/chat",
            "GET  /api/chat/history?session_id=xxx",
            "GET  /api/corpus",
            "POST /api/corpus/upload",
            "POST /api/corpus/text",
            "DELETE /api/corpus/{doc_id}",
            "POST /api/corpus/{doc_id}/reingest",
        ],
    }


@app.get("/api/health", response_model=HealthResponse, tags=["系统"], summary="健康检查")
def health():
    from .services.pipeline import get_rag_service
    from .services.vectorstore import get_vector_store

    svc = get_rag_service()
    return HealthResponse(
        status="ok",
        database=_DB_LABEL.get(ACTIVE_DB_TYPE, ACTIVE_DB_TYPE),
        vector_store=get_vector_store().name,
        doc_count=get_vector_store().count(),
        llm_provider=svc.llm.name,
        embedding_provider=svc.embedding.name,
    )
