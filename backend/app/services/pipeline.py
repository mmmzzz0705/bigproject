"""AI 应用层服务工厂：按 PIPELINE 配置选择 native / langchain 实现。"""
from __future__ import annotations

from ..config import settings


def get_rag_service():
    """返回全局唯一的 RAG 服务实例。"""
    if (settings.PIPELINE or "native").lower() == "langchain":
        try:
            from .langchain_rag import LangChainRAGService

            return LangChainRAGService()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] LangChain 流水线不可用（{e}），回退到原生实现")
    from .rag import RAGService

    return RAGService()
