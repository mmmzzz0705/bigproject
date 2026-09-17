"""向量库封装：内存（numpy，可持久化）/ Chroma。"""
from __future__ import annotations

import json
import math
import re
import threading
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..config import BASE_DIR, settings

_CJK_RUN = re.compile(r"[\u4e00-\u9fa5]+")
_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文按字（单字 + 二元组）切分，英文数字按词切分。"""
    t = (text or "").lower()
    toks: list[str] = list(_WORD.findall(t))
    for run in _CJK_RUN.findall(t):
        toks.extend(run)                                   # 单字
        toks.extend(run[i : i + 2] for i in range(len(run) - 1))  # 二元组
    return toks


class BM25Index:
    """轻量级 BM25 关键词索引：弥补哈希向量语义能力不足，实现混合检索。"""

    K1, B = 1.5, 0.75

    def __init__(self):
        self.tf: list[dict[str, int]] = []
        self.lens: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.avg_len = 0.0

    def add(self, text: str) -> None:
        toks = tokenize(text)
        idx = len(self.tf)
        freq: dict[str, int] = defaultdict(int)
        for tk in toks:
            freq[tk] += 1
        self.tf.append(dict(freq))
        self.lens.append(len(toks))
        for tk, c in freq.items():
            self.postings[tk].append((idx, c))
        self.avg_len = sum(self.lens) / max(len(self.lens), 1)

    def search(self, query: str) -> np.ndarray:
        n = len(self.tf)
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        scores = np.zeros(n, dtype=np.float32)
        q_tokens = set(tokenize(query))
        for tk in q_tokens:
            postings = self.postings.get(tk)
            if not postings:
                continue
            df = len(postings)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for idx, tf in postings:
                dl = self.lens[idx] or 1
                denom = tf + self.K1 * (1 - self.B + self.B * dl / (self.avg_len or 1))
                scores[idx] += idf * (tf * (self.K1 + 1)) / denom
        return scores

    def clear(self) -> None:
        self.tf, self.lens, self.postings = [], [], defaultdict(list)
        self.avg_len = 0.0


@dataclass
class Hit:
    """检索结果"""

    text: str
    doc_id: str = ""
    doc_name: str = ""
    section: str = ""
    score: float = 0.0
    meta: dict = field(default_factory=dict)
    vector_score: float = 0.0
    keyword_score: float = 0.0


class BaseVectorStore(ABC):
    name = "base"
    # 降级标记：配置的向量库（Milvus/Chroma）初始化失败、退到空的内存库时为 True。
    # 上层据此把"检索不到"报成**服务故障**而不是"知识库没有该政策"——
    # 否则一次连不上向量库，所有问题都会答"暂无该业务相关政策"，把故障说成缺知识。
    degraded = False

    @abstractmethod
    def add(self, texts: list[str], metas: list[dict], ids: list[str] | None = None) -> int: ...

    @abstractmethod
    def search(
        self, query_vec: np.ndarray, top_k: int = 4, query_text: str | None = None
    ) -> list[Hit]: ...

    @abstractmethod
    def count(self) -> int: ...

    def clear(self) -> None:  # 可选实现
        raise NotImplementedError

    def delete_by_doc_id(self, doc_id: str) -> int:
        """删除整篇文档的全部片段，返回删除条数。

        工作台的"删除语料"依赖它：只删元数据库而不清向量，检索仍会命中已删文档。
        """
        raise NotImplementedError(f"{self.name} 不支持按文档删除")

    def doc_stats(self) -> dict[str, int]:
        """{doc_id: 片段数}，用于列表页展示每篇语料的切块量。"""
        return {}

    def fetch_doc(self, doc_id: str, limit: int = 50) -> list[Hit]:
        """取出某篇文档的片段（按 chunk_index 排序），用于工作台的"切分预览"。

        和 fetch_section 的区别：它不限章节，看的是整篇被切成了什么样子 ——
        切得碎不碎、有没有把材料表切断、章节名认对了没，一眼就能看出来。
        """
        return []

    def fetch_section(self, doc_id: str, section: str, limit: int = 64) -> list[Hit]:
        """取出某文档某章节的**全部**片段。

        为什么需要它：search() 会按 (doc_id, section) 去重，一个章节只留一条。
        对「材料清单」这种上万字、被切成几十段的章节，去重等于只留下分数最高的那一段
        —— 而分数最高的往往是"填报须知/备注"这类噪声段，一条材料都解析不出来，
        结果"需要哪些材料"答出 0 条必备材料。
        要拿到真正含材料表的那一段，只能绕过去重、把同章节的兄弟片段都取出来。
        默认实现返回空列表，由各实现按需覆盖。
        """
        return []


class MemoryVectorStore(BaseVectorStore):
    """内存向量库：余弦相似度检索，结果持久化到本地 JSON，重启免重建。"""

    name = "memory"

    def __init__(self, persist_path: str | Path | None = None):
        self._path = Path(persist_path) if persist_path else BASE_DIR / "data" / "vector_store.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.ids: list[str] = []
        self.texts: list[str] = []
        self.metas: list[dict] = []
        self.matrix = np.zeros((0, 0), dtype=np.float32)
        self.bm25 = BM25Index()
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            ids = data.get("ids", [])
            texts = data.get("texts", [])
            metas = data.get("metas", [])
            vecs = data.get("vectors", [])
            matrix = np.array(vecs, dtype=np.float32) if vecs else np.zeros((0, 0), dtype=np.float32)

            # 维度校验：换了 Embedding 模型（如 2560 维 -> 768 维）后，
            # 磁盘上的旧向量与 VECTOR_DIM 不一致。Milvus 路径会因为维度不匹配
            # 直接删集合重建，而这里如果不校验，会**静默沿用旧向量**：
            # count() > 0 导致启动时不导入，检索时新查询向量与旧库做点积，
            # 分数全部失真且不报任何错。所以宁可丢弃重建。
            if matrix.ndim == 2 and matrix.shape[0] and matrix.shape[1] != settings.VECTOR_DIM:
                print(
                    f"[warn] 本地向量库维度 {matrix.shape[1]} 与 VECTOR_DIM="
                    f"{settings.VECTOR_DIM} 不一致（Embedding 模型换过？），丢弃重建"
                )
                self._reset()
                return

            self.ids, self.texts, self.metas, self.matrix = ids, texts, metas, matrix
            for t in self.texts:
                self.bm25.add(t)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 向量库加载失败，将重建：{e}")
            self._reset()

    def _reset(self) -> None:
        """清空内存态与 BM25，并把磁盘上的旧库改名留档。"""
        self.ids, self.texts, self.metas = [], [], []
        self.matrix = np.zeros((0, 0), dtype=np.float32)
        self.bm25 = BM25Index()
        if self._path.exists():
            try:
                backup = self._path.with_suffix(self._path.suffix + ".bak")
                self._path.replace(backup)
                print(f"[warn] 旧向量库已备份为 {backup.name}")
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 旧向量库备份失败：{e}")

    def _save(self) -> None:
        try:
            payload = {
                "ids": self.ids,
                "texts": self.texts,
                "metas": self.metas,
                "vectors": self.matrix.astype(float).round(6).tolist(),
            }
            self._path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 向量库持久化失败：{e}")

    # ---------- 接口 ----------
    def add(self, texts: list[str], metas: list[dict], ids: list[str] | None = None) -> int:
        if not texts:
            return 0
        emb = get_embedding()
        vecs = emb.embed(texts)
        with self._lock:
            if self.matrix.size == 0:
                self.matrix = vecs
            else:
                self.matrix = np.vstack([self.matrix, vecs])
            for i, t in enumerate(texts):
                self.ids.append((ids[i] if ids else None) or uuid.uuid4().hex)
                self.texts.append(t)
                self.metas.append(metas[i] if i < len(metas) else {})
                self.bm25.add(t)
            self._save()
        return len(texts)

    def search(
        self,
        query_vec: np.ndarray,
        top_k: int = 4,
        query_text: str | None = None,
        doc_filter: str | None = None,
    ) -> list[Hit]:
        """混合检索：向量余弦 + BM25 关键词，兼顾语义与政务术语精确匹配。"""
        if self.matrix.size == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        vec_scores = self.matrix @ q  # 已归一化 -> 余弦相似度

        if query_text and self.bm25.tf:
            kw = self.bm25.search(query_text)
            # 绝对尺度压缩到 0~1：保留区分度，避免相对归一化把噪声抬到满分
            kw_norm = kw / (kw + 8.0)
            # 只有问题里确实出现政务术语时才做混合。口语化泛问的 BM25 全是
            # 单二元组噪声分，掺进来会把真正的语义命中挤下去（详见
            # MilvusVectorStore.search 的同名注释）。
            kw_strong = bool(kw.size) and float(kw.max()) >= settings.KEYWORD_MIN_SCORE
        else:
            kw_norm = np.zeros_like(vec_scores)
            kw_strong = False

        fused = 0.45 * vec_scores + 0.55 * kw_norm if kw_strong else vec_scores

        # 取候选池后按"文档 + 章节"去重，保证召回片段覆盖多个章节
        pool = np.argsort(-fused)[: max(top_k * 5, 15)]
        if doc_filter:  # 限定在同一文档内检索（用于结构化字段补全）
            pool = [i for i in pool if self.metas[i].get("doc_id", "") == doc_filter]
        seen: set[tuple[str, str]] = set()
        picked: list[int] = []
        for i in pool:
            key = (self.metas[i].get("doc_id", ""), self.metas[i].get("section", ""))
            if key in seen:
                continue
            seen.add(key)
            picked.append(int(i))
            if len(picked) >= max(top_k, 1):
                break

        return [
            Hit(
                text=self.texts[i],
                doc_id=self.metas[i].get("doc_id", ""),
                doc_name=self.metas[i].get("doc_name", ""),
                section=self.metas[i].get("section", ""),
                score=float(fused[i]),
                meta=self.metas[i],
                vector_score=float(vec_scores[i]),
                keyword_score=float(kw[i]) if kw.size else 0.0,
            )
            for i in picked
        ]

    def fetch_doc(self, doc_id: str, limit: int = 50) -> list[Hit]:
        pairs = [
            (i, m)
            for i, m in enumerate(self.metas)
            if str(m.get("doc_id", "")) == str(doc_id)
        ]
        pairs.sort(key=lambda x: int(x[1].get("chunk_index", x[0]) or 0))
        return [
            Hit(
                text=self.texts[i],
                doc_id=doc_id,
                doc_name=str(m.get("doc_name", "")),
                section=str(m.get("section", "")),
                meta=dict(m),
            )
            for i, m in pairs[: max(limit, 1)]
        ]

    def fetch_section(self, doc_id: str, section: str, limit: int = 64) -> list[Hit]:
        out: list[Hit] = []
        for i, meta in enumerate(self.metas):
            if meta.get("doc_id") != doc_id or meta.get("section") != section:
                continue
            out.append(
                Hit(
                    text=self.texts[i],
                    doc_id=doc_id,
                    doc_name=str(meta.get("doc_name", "")),
                    section=section,
                    score=0.0,
                    meta=dict(meta),
                )
            )
            if len(out) >= limit:
                break
        return out

    def count(self) -> int:
        return len(self.texts)

    def clear(self) -> None:
        with self._lock:
            self.ids, self.texts, self.metas = [], [], []
            self.matrix = np.zeros((0, 0), dtype=np.float32)
            self.bm25.clear()
            self._save()

    def delete_by_doc_id(self, doc_id: str) -> int:
        doc_id = str(doc_id)
        with self._lock:
            keep = [i for i, m in enumerate(self.metas) if str(m.get("doc_id", "")) != doc_id]
            removed = len(self.metas) - len(keep)
            if removed <= 0:
                return 0
            self.ids = [self.ids[i] for i in keep]
            self.texts = [self.texts[i] for i in keep]
            self.metas = [self.metas[i] for i in keep]
            if self.matrix.shape[0] == len(keep) + removed:
                self.matrix = self.matrix[keep]
            # BM25 索引只支持追加，没有增量删除，只能按剩余文本重建
            self.bm25 = BM25Index()
            for t in self.texts:
                self.bm25.add(t)
            self._save()
            return removed

    def doc_stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for m in self.metas:
            d = str(m.get("doc_id", ""))
            out[d] = out.get(d, 0) + 1
        return out


class ChromaVectorStore(BaseVectorStore):
    """Chroma 向量库（生产推荐，需 pip install chromadb）。"""

    name = "chroma"

    def __init__(self, persist_dir: str | None = None, collection: str | None = None):
        import chromadb  # 延迟导入

        if settings.CHROMA_HOST:  # 连接独立的 Chroma 服务（容器化部署）
            self.client = chromadb.HttpClient(
                host=settings.CHROMA_HOST, port=settings.CHROMA_PORT
            )
        else:
            self.client = chromadb.PersistentClient(path=persist_dir or settings.chroma_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection or settings.CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, texts: list[str], metas: list[dict], ids: list[str] | None = None) -> int:
        if not texts:
            return 0
        vecs = get_embedding().embed(texts)
        _ids = ids or [uuid.uuid4().hex for _ in texts]
        self.collection.add(
            ids=_ids,
            documents=texts,
            embeddings=[v.tolist() for v in vecs],
            metadatas=[{k: str(v) for k, v in m.items()} for m in metas],
        )
        return len(texts)

    def search(self, query_vec: np.ndarray, top_k: int = 4, query_text: str | None = None) -> list[Hit]:
        # Chroma 走纯向量检索；如需关键词能力可在上层叠加 BM25
        res = self.collection.query(
            query_embeddings=[np.asarray(query_vec, dtype=float).reshape(-1).tolist()],
            n_results=max(top_k, 1),
        )
        hits: list[Hit] = []
        docs = res.get("documents") or [[]]
        metas = res.get("metadatas") or [[]]
        dists = res.get("distances") or [[]]
        for i, doc in enumerate(docs[0]):
            meta = metas[0][i] if i < len(metas[0]) else {}
            dist = dists[0][i] if i < len(dists[0]) else 0.0
            hits.append(
                Hit(
                    text=doc or "",
                    doc_id=meta.get("doc_id", ""),
                    doc_name=meta.get("doc_name", ""),
                    section=meta.get("section", ""),
                    score=float(1 - dist),
                    meta=meta,
                )
            )
        return hits

    def count(self) -> int:
        return self.collection.count()

    def clear(self) -> None:
        self.client.delete_collection(settings.CHROMA_COLLECTION)
        self.collection = self.client.get_or_create_collection(
            name=settings.CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"}
        )

    def delete_by_doc_id(self, doc_id: str) -> int:
        before = self.count()
        self.collection.delete(where={"doc_id": str(doc_id)})
        return max(before - self.count(), 0)

    def fetch_doc(self, doc_id: str, limit: int = 50) -> list[Hit]:
        got = self.collection.get(where={"doc_id": str(doc_id)}) or {}
        rows = []
        for doc, meta in zip(got.get("documents") or [], got.get("metadatas") or []):
            meta = meta or {}
            rows.append(
                Hit(
                    text=doc or "",
                    doc_id=str(meta.get("doc_id", "")),
                    doc_name=str(meta.get("doc_name", "")),
                    section=str(meta.get("section", "")),
                    meta=dict(meta),
                )
            )
        rows.sort(key=lambda h: int(h.meta.get("chunk_index", 0) or 0))
        return rows[: max(limit, 1)]

    def doc_stats(self) -> dict[str, int]:
        got = self.collection.get() or {}
        out: dict[str, int] = {}
        for m in got.get("metadatas") or []:
            d = str((m or {}).get("doc_id", ""))
            out[d] = out.get(d, 0) + 1
        return out


_store: BaseVectorStore | None = None
_embedding = None

# 启动阶段连接外部向量库的重试策略。
# 为什么必须重试：docker compose 里后端与 Milvus/PG 是**同时**启动的，后端常常比
# Milvus 早几百毫秒就绪（实测 gov-backend 05:20:32 起、milvus 05:20:33 起，
# 而 Milvus standalone 要几十秒才能接受连接）。一次性初始化失败就会永久降级成
# 空的内存向量库 —— 之后每个问题都答"知识库暂无该业务政策"，但 /api/health
# 依然返回 200，看着一切正常，极难排查。
VECTOR_STORE_RETRY = 6        # 重试次数
VECTOR_STORE_RETRY_WAIT = 5   # 每次间隔（秒）


def _connect_with_retry(factory, label: str) -> BaseVectorStore | None:
    """带重试地构造向量库；全部失败返回 None（由调用方决定降级）。"""
    import time

    last: Exception | None = None
    for i in range(1, VECTOR_STORE_RETRY + 1):
        try:
            return factory()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < VECTOR_STORE_RETRY:
                print(
                    f"[warn] {label} 第 {i}/{VECTOR_STORE_RETRY} 次连接失败，"
                    f"{VECTOR_STORE_RETRY_WAIT}s 后重试：{e}"
                )
                time.sleep(VECTOR_STORE_RETRY_WAIT)
    print(f"[error] {label} 连续 {VECTOR_STORE_RETRY} 次连接失败：{last}")
    return None


def get_embedding():
    """全局单例 Embedding。"""
    global _embedding
    if _embedding is None:
        from .embeddings import build_embedding

        _embedding = build_embedding()
        print(f"[init] Embedding provider = {_embedding.name}")
    return _embedding


def get_vector_store() -> BaseVectorStore:
    """全局单例向量库；Chroma / Milvus 不可用时自动降级为内存向量库（并标记 degraded）。"""
    global _store
    if _store is None:
        kind = (settings.VECTOR_STORE or "memory").lower()
        if kind == "milvus":
            from .milvus_store import MilvusVectorStore

            _store = _connect_with_retry(MilvusVectorStore, "Milvus")
            if _store is None:
                print(
                    "[warn] 降级为内存向量库。内存库为空时所有提问都会答『暂无该政策』"
                    "——那是假象，实际是向量库没连上。请检查 MILVUS_HOST/PORT 与容器网络。"
                )
                _store = MemoryVectorStore()
                _store.degraded = True
        elif kind == "chroma":
            _store = _connect_with_retry(ChromaVectorStore, "Chroma")
            if _store is None:
                print("[warn] 降级为内存向量库。")
                _store = MemoryVectorStore()
                _store.degraded = True
        else:
            _store = MemoryVectorStore()
        print(f"[init] Vector store = {_store.name} (docs={_store.count()})")
    return _store
