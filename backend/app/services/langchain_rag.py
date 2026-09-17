"""LangChain 版 RAG 服务：检索走 LangChain Retriever，生成走 LCEL 链。

与原生实现共享"相关性判定 / 章节补全 / 材料抽取 / 结构校验"逻辑，
保证两条实现链路行为一致，可随时通过 PIPELINE 配置切换。
"""
from __future__ import annotations

from .llm import SYSTEM_PROMPT
from .prompts import QA_TEMPLATE, NO_HIT_ANSWER, build_context, build_history
from .rag import RAGService
from .vectorstore import Hit


class LangChainRAGService(RAGService):
    """AI 应用层（LangChain）实现。"""

    pipeline_name = "langchain"

    def _init(self) -> None:
        from .langchain_pipeline import (
            LANGCHAIN_AVAILABLE,
            GovEmbeddings,
            GovVectorRetriever,
            build_qa_chain,
        )

        super()._init()
        self.langchain_available = LANGCHAIN_AVAILABLE
        if not LANGCHAIN_AVAILABLE:
            print("[warn] LangChain 不可用，回退到原生检索与生成实现")
            self.retriever = None
            self.chain = None
            return

        self.retriever = GovVectorRetriever(store=self.store, embedding=self.embedding)
        self.embeddings = GovEmbeddings(self.embedding)
        self.chain = build_qa_chain(SYSTEM_PROMPT)
        print("[init] LangChain pipeline ready (retriever + LCEL chain)")

    # ---------------- 检索：LangChain Retriever ----------------
    def retrieve(self, question: str, top_k: int | None = None) -> list[Hit]:
        if not getattr(self, "retriever", None):
            return super().retrieve(question, top_k)
        docs = self.retriever.invoke(question)
        hits: list[Hit] = []
        for d in docs:
            m = d.metadata or {}
            hits.append(
                Hit(
                    text=d.page_content,
                    doc_id=m.get("doc_id", ""),
                    doc_name=m.get("doc_name", ""),
                    section=m.get("section", ""),
                    score=float(m.get("score", 0.0)),
                    meta=m,
                    vector_score=float(m.get("vector_score", 0.0)),
                    keyword_score=float(m.get("keyword_score", 0.0)),
                )
            )
        return hits[: top_k or len(hits)]

    # ---------------- 生成：LCEL 链 ----------------
    def generate(self, question: str, history, hits: list[Hit]) -> dict:
        if not getattr(self, "chain", None):
            return super().generate(question, history, hits)

        from .llm import BaseLLM

        prompt = QA_TEMPLATE.format(
            context=build_context(hits),
            history=build_history(history),
            question=question,
            no_hit=NO_HIT_ANSWER.replace("\n", "\\n"),
        )
        raw = self.chain.invoke({"prompt": prompt})
        return BaseLLM.parse(raw, hits)
