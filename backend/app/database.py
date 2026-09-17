"""数据库连接与会话管理。

支持 PostgreSQL（默认）/ MySQL / SQLite。
当配置的关系库不可达时，自动降级为本地 SQLite，保证服务可启动。
"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import BASE_DIR, settings

logger = logging.getLogger(__name__)


def _sqlite_url() -> str:
    path = (BASE_DIR / settings.SQLITE_PATH).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # SQLite 需要关闭同线程检查（FastAPI 多线程处理请求）
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def _build_engine() -> tuple[Engine, str]:
    url = settings.db_url
    if url.startswith("sqlite"):
        return _make_engine(url), "sqlite"
    try:
        eng = _make_engine(url)
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return eng, settings.db_type
    except Exception as exc:  # 关系库不可达 → 降级 SQLite
        logger.warning(
            "[database] %s 连接失败，已自动降级为 SQLite：%s",
            settings.db_type, exc,
        )
        return _make_engine(_sqlite_url()), "sqlite"


engine, ACTIVE_DB_TYPE = _build_engine()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

Base = declarative_base()


def get_db():
    """FastAPI 依赖注入：每个请求一个数据库会话，结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（表不存在时）。生产环境建议使用 sql/schema.sql 建表。"""
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
