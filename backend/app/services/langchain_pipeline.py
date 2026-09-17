"""AI 应用层（LangChain 实现）

对应《系统设计》第三章"AI 应用层"的三个子模块：
- 离线文档预处理子模块：LangChain Document Loaders + TextSplitter
- 向量检索子模块：自定义 Retriever（内部走向量库混合检索）
- 大模型生成子模块：ChatPromptTemplate | ChatModel | 输出解析（LCEL 链）

说明：组件缺失或配置不完整时，各子模块自动回退到 app/services 下的原生实现，
保证系统始终可运行。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import settings
from ..utils.text import clean_text, split_sections

try:  # LangChain 为可选依赖
    from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.retrievers import BaseRetriever
    from langchain_core.runnables import Runnable
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    LANGCHAIN_AVAILABLE = True
except Exception as _e:  # noqa: BLE001
    LANGCHAIN_AVAILABLE = False
    LANGCHAIN_IMPORT_ERROR = str(_e)

    class Embeddings:  # type: ignore[no-redef]
        pass

    class BaseRetriever:  # type: ignore[no-redef]
        pass

    class StrOutputParser:  # type: ignore[no-redef]
        pass

    Document = None  # type: ignore[assignment]


# ---------------- 1. 离线文档预处理子模块 ----------------
def load_text(path: Path) -> str:
    """使用 LangChain Document Loaders 读取 PDF / Word / TXT / Markdown。"""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        docs = PyPDFLoader(str(path)).load()
    elif suffix == ".docx":
        docs = Docx2txtLoader(str(path)).load()
    else:
        docs = TextLoader(str(path), encoding="utf-8").load()
    return "\n".join(d.page_content for d in docs)


def build_splitter():
    """中文政务文本切分器：优先按段落/句读断开，保留重叠窗口。"""
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", "。", "；", "！", "？", "，", " ", ""],
    )


def build_chunks(text: str, doc_title: str = "") -> list[tuple[str, str]]:
    """先按章节切分，再用 LangChain 文本切分器分块，并保留上下文头。"""
    splitter = build_splitter()
    out: list[tuple[str, str]] = []
    for section, body in split_sections(text):
        header = "\n".join(x for x in (doc_title, section) if x)
        pieces = splitter.split_text(body) if body else []
        for piece in pieces:
            out.append((section, f"{header}\n{piece}" if header else piece))
    return out


def load_and_chunk(path: Path, doc_title: str = "") -> list[tuple[str, str]]:
    """加载 + 清洗 + 分块的完整链路。"""
    return build_chunks(clean_text(load_text(path)), doc_title=doc_title)


# ---------------- 2. 向量检索子模块 ----------------
class GovEmbeddings(Embeddings):
    """把项目内 Embedding provider 适配为 LangChain Embeddings 接口。"""

    def __init__(self, provider=None):
        self.provider = provider

    def _get(self):
        if self.provider is None:
            from .vectorstore import get_embedding

            self.provider = get_embedding()
        return self.provider

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._get().embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return list(map(float, self._get().embed([text])[0]))


class GovVectorRetriever(BaseRetriever):
    """Retriever：调用向量库做向量 + 关键词混合检索，返回 LangChain Document。"""

    store: Any = None
    embedding: Any = None
    top_k: int = settings.TOP_K

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list:
        from .vectorstore import get_embedding, get_vector_store

        store = self.store or get_vector_store()
        emb = self.embedding or get_embedding()
        vec = emb.embed([query])[0]
        hits = store.search(vec, self.top_k, query_text=query)
        return [
            Document(
                page_content=h.text,
                metadata={
                    "doc_id": h.doc_id,
                    "doc_name": h.doc_name,
                    "section": h.section,
                    "score": h.score,
                    "vector_score": h.vector_score,
                    "keyword_score": h.keyword_score,
                    "source": h.meta.get("source", ""),
                },
            )
            for h in hits
        ]


# ---------------- 3. 大模型生成子模块 ----------------
def build_chat_model() -> BaseChatModel | None:
    """构建 OpenAI 兼容的 ChatModel（支持通义千问兼容模式）。"""
    from langchain_openai import ChatOpenAI

    provider = (settings.LLM_PROVIDER or "").lower()
    if provider == "dashscope" and settings.DASHSCOPE_API_KEY:
        return ChatOpenAI(
            model=settings.DASHSCOPE_MODEL,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_BASE_URL,
            temperature=settings.TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
        )
    if provider in ("openai", "dashscope") and settings.OPENAI_API_KEY:
        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=settings.TEMPERATURE,
            timeout=settings.LLM_TIMEOUT,
        )
    return None


def build_qa_chain(system_prompt: str) -> Runnable | None:
    """LCEL 链：Prompt | ChatModel | 字符串输出。"""
    model = build_chat_model()
    if model is None:
        return None
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", "{prompt}")]
    )
    return prompt | model | StrOutputParser()
