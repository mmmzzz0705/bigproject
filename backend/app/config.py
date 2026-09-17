"""全局配置：所有参数均可通过环境变量 / .env 覆盖。

设计要点：任何外部依赖（MySQL、Chroma、大模型 API）缺失时，
系统自动降级为可运行的本地实现，保证演示与开发不中断。
"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 基础 ----------
    APP_NAME: str = "政务智能问答与办事引导系统"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ORIGINS: str = "*"

    # ---------- 数据库 ----------
    # auto：填了 DB_HOST 就用关系库（按 DB_TYPE 决定 PostgreSQL / MySQL），否则降级 SQLite
    # postgresql：本机 PostgreSQL（推荐，本项目默认）
    # mysql：MySQL / MariaDB
    DB_TYPE: str = "auto"                 # auto | postgresql | mysql | sqlite
    DB_HOST: str = ""
    DB_PORT: int = 0                      # 0 = 按 DB_TYPE 取默认端口（pg 5432 / mysql 3306）
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "gov_qa"
    DB_CHARSET: str = "utf8mb4"           # 仅 MySQL 使用
    SQLITE_PATH: str = "data/app.db"

    # ---------- AI 应用层实现 ----------
    PIPELINE: str = "native"              # native（自研）| langchain（LangChain 链）

    # ---------- 向量库 ----------
    VECTOR_STORE: str = "memory"          # memory | chroma | milvus
    VECTOR_DIM: int = 1024                # 向量维度（需与 Embedding 模型一致）
    CHROMA_PERSIST_DIR: str = "data/chroma"
    CHROMA_COLLECTION: str = "gov_docs"
    # 容器化部署时填写 Chroma 服务地址（如 chroma）；留空则使用本地持久化目录
    CHROMA_HOST: str = ""
    CHROMA_PORT: int = 8000
    # Milvus 向量库
    MILVUS_HOST: str = "127.0.0.1"
    MILVUS_PORT: int = 19530
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_DB: str = "default"
    MILVUS_COLLECTION: str = "gov_docs"

    # ---------- Embedding ----------
    # hash | openai | dashscope（OpenAI 兼容文本向量，当前默认）
    #       | dashscope_native（多模态向量原生端点）
    #         qwen3.7-text-embedding-flash -> 1024 维（默认，当前使用）
    #         qwen3.7-text-embedding-flash -> 也支持 768 / 512 / 256
    #         tongyi-embedding-vision-flash -> 768 维（多模态，走 dashscope_native）
    #         qwen3-vl-embedding            -> 2560 维（多模态，走 dashscope_native）
    # 换模型必须同步改 VECTOR_DIM：Milvus 发现维度不一致会**直接删集合重建**。
    EMBEDDING_PROVIDER: str = "hash"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"
    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_EMBED_MODEL: str = "qwen3.7-text-embedding-flash"
    # 多模态向量【原生端点】（tongyi-embedding-vision-flash / qwen3-vl-embedding
    # 都不支持 OpenAI 兼容模式，只能走这里）
    DASHSCOPE_NATIVE_EMBED_URL: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    EMBED_WORKERS: int = 6        # 并发数（原生接口一次只能提交一条；兼容模式按批提交）
    # Embedding 必须用独立超时：不能复用 LLM_TIMEOUT(300s)，
    # 否则一次挂起会阻塞 300s × 重试次数，整个请求线程被拖死。
    EMBED_TIMEOUT: int = 30

    # ---------- 大模型 ----------
    LLM_PROVIDER: str = "extractive"      # extractive | openai | dashscope
    OPENAI_MODEL: str = "gpt-4o-mini"
    DASHSCOPE_MODEL: str = "qwen-plus"
    TEMPERATURE: float = 0.2
    # 推理类模型（qwen3.x）单次可达数十秒，超时需放宽
    LLM_TIMEOUT: int = 300
    # 推理类模型是否开启"深度思考"。政务问答追求低延迟，默认关闭
    LLM_ENABLE_THINKING: bool = False
    LLM_MAX_TOKENS: int = 4096       # 材料清单较长，放开输出长度避免被截断
    # 思考模式下限制思考 token 数（qwen3 的 thinking_budget）。
    # 不限制时实测单轮可达 140s+；给 1024 后降到 10s 量级，答案质量无明显下降。
    # 设为 0 = 不传该参数（由服务端决定）
    LLM_THINKING_BUDGET: int = 1024

    # ---------- RAG ----------
    TOP_K: int = 4
    SIMILARITY_THRESHOLD: float = 0.22      # 融合分粗筛阈值（旧口径，保留兼容）
    KEYWORD_MIN_SCORE: float = 7.0          # BM25 绝对分：低于此值视为无关
    # 向量余弦绝对分：低于此值视为无关。**随 Embedding 模型变化，必须实测标定**
    # （scripts/calibrate_gate.py + scripts/probe_gate.py）。
    # 实测（1024 维 qwen3.7-text-embedding-flash / 841 片段，2026-09-15）：
    #   纯域外 0.335~0.356，像政务未收录 0.501~0.739，
    #   口语化泛问 0.418~0.838，标准问法 0.665~0.973。
    # 取 0.45 而非标定推荐值 0.752：后者会把口语化泛问全挡在门外（它们关键词分≈0，
    # 只能靠向量分过闸），放行后还有 VAGUE_VECTOR_MAX 兜底走候选引导。
    VECTOR_MIN_SCORE: float = 0.45
    # 融合分（向量 + 关键词）兜底阈值：覆盖"语义中等 + 政务术语强命中"的问法。
    FUSED_MIN_SCORE: float = 0.62
    # 泛问引导阈值：Top-1 向量分低于此值（且关键词没强命中）说明问题太概括
    # （没说清办哪个事项），不硬答一个具体事项，而是列出候选事项让用户确认。
    VAGUE_VECTOR_MAX: float = 0.60
    MAX_HISTORY_TURNS: int = 5
    MAX_CONTEXT_CHARS: int = 3000
    MAX_QUESTION_LEN: int = 1000

    # ---------- 离线预处理 ----------
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    DOCS_DIR: str = "data/docs"
    AUTO_INGEST_ON_STARTUP: bool = True

    # ---------- 工作台：用户上传语料 ----------
    # 上传语料与内置语料（DOCS_DIR）**必须分目录**：
    # 容器里 backend/data/corpus 是以只读方式挂载的基准语料，删不掉也不该被写；
    # 上传的语料要支持删除，只能落在可写目录。两个目录混在一起，
    # 删除逻辑就得靠文件名猜归属，迟早误删基准语料。
    UPLOAD_DIR: str = "data/uploads"
    MAX_UPLOAD_MB: int = 10
    # 工作台写操作凭证。**留空 = 不校验**（内网/演示部署保持零配置）。
    # 一旦配置，/api/corpus 下所有接口都必须在请求头带 X-Workbench-Token ——
    # 否则任何能访问前端的人都能把整个知识库删空。
    # 前端配套配 VITE_WORKBENCH_TOKEN（同一个值），留空则不发该头。
    CORPUS_WRITE_TOKEN: str = ""
    # 粘贴入库的正文上限（字符）。一篇政务指南通常 1~3 万字，20 万字已是极端值；
    # 再大不只是慢，单次 Embedding 调用会直接超时。
    MAX_CORPUS_TEXT_CHARS: int = 200_000

    @property
    def db_type(self) -> str:
        """推断实际使用的数据库类型：postgresql | mysql | sqlite"""
        t = (self.DB_TYPE or "auto").strip().lower()
        if t in ("postgresql", "postgres", "pg"):
            return "postgresql"
        if t in ("mysql", "mariadb"):
            return "mysql"
        if t == "sqlite":
            return "sqlite"
        # auto：有 DB_HOST 时优先 PostgreSQL（本机环境默认），否则 SQLite
        if self.DB_HOST:
            return "postgresql"
        return "sqlite"

    @property
    def db_port(self) -> int:
        if self.DB_PORT:
            return self.DB_PORT
        return 5432 if self.db_type == "postgresql" else 3306

    @property
    def db_url(self) -> str:
        """默认 PostgreSQL（本机 bigpg:5433），缺失时降级 SQLite。"""
        t = self.db_type
        if t == "postgresql":
            pwd = quote_plus(self.DB_PASSWORD)
            return (
                f"postgresql+psycopg2://{self.DB_USER}:{pwd}@"
                f"{self.DB_HOST}:{self.db_port}/{self.DB_NAME}"
            )
        if t == "mysql":
            pwd = quote_plus(self.DB_PASSWORD)
            return (
                f"mysql+pymysql://{self.DB_USER}:{pwd}@"
                f"{self.DB_HOST}:{self.db_port}/{self.DB_NAME}"
                f"?charset={self.DB_CHARSET}"
            )
        path = (BASE_DIR / self.SQLITE_PATH).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path.as_posix()}"

    @property
    def docs_dir(self) -> Path:
        p = Path(self.DOCS_DIR)
        return p if p.is_absolute() else (BASE_DIR / p)

    @property
    def upload_dir(self) -> Path:
        """用户上传语料的落盘目录（自动创建）。"""
        p = Path(self.UPLOAD_DIR)
        p = p if p.is_absolute() else (BASE_DIR / p)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def chroma_dir(self) -> str:
        p = Path(self.CHROMA_PERSIST_DIR)
        p = p if p.is_absolute() else (BASE_DIR / p)
        p.mkdir(parents=True, exist_ok=True)
        return str(p)

    @property
    def cors_origins(self) -> list[str]:
        v = self.CORS_ORIGINS.strip()
        if not v or v == "*":
            return ["*"]
        return [i.strip() for i in v.split(",") if i.strip()]

    @property
    def using_mysql(self) -> bool:
        return self.db_type == "mysql"

    @property
    def using_postgres(self) -> bool:
        return self.db_type == "postgresql"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
