"""Milvus 向量库：与本机已部署的 Milvus（standalone）对接。

设计说明
--------
1. 向量部分由 Milvus 负责（COSINE 度量 + AUTOINDEX 索引，可支撑百万级片段）；
2. 关键词部分（BM25）在进程内维护一份轻量索引，首次检索时从 Milvus 全量拉取文本构建，
   新增/清空时失效重建 —— 从而实现与内存向量库完全一致的「向量 + 关键词」混合检索；
3. 支持直接写入「已有的预计算向量」（vectors 参数），避免重复调用 Embedding 接口。
"""
from __future__ import annotations

import threading
import uuid
from typing import Iterable

import numpy as np

from ..config import settings
from .vectorstore import BM25Index, BaseVectorStore, Hit

MAX_TEXT_LEN = 8000      # Milvus VARCHAR 上限（建表时声明 8192）
MAX_STR_LEN = 512        # 标量字段长度
PAGE = 1000              # 全量拉取分页大小

# 集合加载超时（秒）。Milvus 侧段文件损坏或本地存储路径与当前镜像版本不一致时，
# load_collection() 会**永久阻塞不返回**（实测 >5 分钟），把整个后端卡在 lifespan
# 启动阶段 —— 端口不监听、healthcheck 全红，比"检索不到"严重得多。
# 因此必须设上限：超时就放弃等待让服务先起来，检索阶段再如实报错。
LOAD_TIMEOUT = 30


class MilvusVectorStore(BaseVectorStore):
    name = "milvus"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        collection: str | None = None,
        dim: int | None = None,
    ):
        from pymilvus import DataType, MilvusClient  # 延迟导入

        self.host = host or settings.MILVUS_HOST
        self.port = port or settings.MILVUS_PORT
        self.collection = collection or settings.MILVUS_COLLECTION
        self.dim = int(dim or settings.VECTOR_DIM)

        kwargs: dict = {"uri": f"http://{self.host}:{self.port}"}
        if settings.MILVUS_USER:
            kwargs["user"] = settings.MILVUS_USER
            kwargs["password"] = settings.MILVUS_PASSWORD
        if settings.MILVUS_DB:
            kwargs["db_name"] = settings.MILVUS_DB

        self.client = MilvusClient(**{k: v for k, v in kwargs.items() if v is not None})
        self.DataType = DataType

        self._lock = threading.RLock()
        self._bm25: BM25Index | None = None
        self._bm25_ids: list[str] = []
        self._snapshot: dict[str, dict] = {}   # id -> 行数据（BM25 镜像的附带缓存）
        self.load_error: str = ""              # 非空表示集合加载失败，当前不可检索

        self._ensure_collection()

    # ---------------- 建表 / 索引 ----------------
    def _load(self) -> None:
        """带超时加载集合。

        加载失败不致命：说明集合当前不可检索（段损坏 / 存储路径不匹配 / querynode 未就绪），
        但服务本身要能起来，让前端收到"检索服务不可用"的准确提示，
        而不是把整个进程挂在启动阶段。
        """
        try:
            self.client.load_collection(self.collection, timeout=LOAD_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            self.load_error = str(e)
            print(
                f"[warn] Milvus 集合 {self.collection} 加载失败或超时（{LOAD_TIMEOUT}s）：{e}\n"
                f"[warn] 该集合当前无法检索。常见原因：段文件损坏、本地存储路径与当前镜像版本不一致。\n"
                f"[warn] 排查：docker logs milvus-standalone | grep -i 'load segment failed'；"
                f"修复：确认语料齐全后 drop 集合重新执行 scripts/ingest.py。"
            )

    def _ensure_collection(self) -> None:
        dt = self.DataType
        if self.client.has_collection(self.collection):
            # 已存在：校验维度是否一致，不一致则重建（避免写入报错）
            try:
                info = self.client.describe_collection(self.collection)
                cur_dim = None
                for f in info.get("fields", []):
                    if f.get("type") == dt.FLOAT_VECTOR or "FLOAT_VECTOR" in str(f.get("type")):
                        cur_dim = int(f.get("params", {}).get("dim") or 0) or None
                if cur_dim and cur_dim != self.dim:
                    print(
                        f"[milvus] 集合 {self.collection} 维度 {cur_dim} 与配置 {self.dim} "
                        f"不一致，已重建"
                    )
                    self.client.drop_collection(self.collection)
                else:
                    self._load()
                    return
            except Exception as e:  # noqa: BLE001
                print(f"[warn] 读取 Milvus 集合信息失败：{e}")

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)
        schema.add_field("id", dt.VARCHAR, max_length=128, is_primary=True)
        schema.add_field("doc_id", dt.VARCHAR, max_length=MAX_STR_LEN)
        schema.add_field("doc_name", dt.VARCHAR, max_length=MAX_STR_LEN)
        schema.add_field("section", dt.VARCHAR, max_length=MAX_STR_LEN)
        schema.add_field("source", dt.VARCHAR, max_length=MAX_STR_LEN)
        schema.add_field("text", dt.VARCHAR, max_length=8192)
        schema.add_field("embedding", dt.FLOAT_VECTOR, dim=self.dim)

        index = self.client.prepare_index_params()
        index.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
        )
        self.client.create_collection(
            collection_name=self.collection, schema=schema, index_params=index
        )
        self._load()

    # ---------------- BM25 镜像 ----------------
    def _ensure_bm25(self) -> None:
        with self._lock:
            if self._bm25 is not None:
                return
            idx = BM25Index()
            ids: list[str] = []
            snap: dict[str, dict] = {}
            rows = self._iter_rows(["id", "text", "doc_id", "doc_name", "section", "source"])
            for r in rows:
                _id = str(r.get("id", ""))
                ids.append(_id)
                snap[_id] = r
                idx.add(r.get("text", "") or "")
            self._bm25_ids = ids
            self._snapshot = snap
            self._bm25 = idx

    def _iter_rows(self, fields: Iterable[str]) -> list[dict]:
        fields = list(fields)
        out: list[dict] = []
        offset = 0
        while True:
            batch = self.client.query(
                collection_name=self.collection,
                filter="",
                output_fields=fields,
                limit=PAGE,
                offset=offset,
            )
            if not batch:
                break
            out.extend(batch)
            if len(batch) < PAGE:
                break
            offset += len(batch)
            if offset > 200000:  # 安全阀
                break
        return out

    def _invalidate(self) -> None:
        self._bm25 = None
        self._bm25_ids = []
        self._snapshot = {}

    # ---------------- 接口 ----------------
    def add(
        self,
        texts: list[str],
        metas: list[dict],
        ids: list[str] | None = None,
        vectors: np.ndarray | list | None = None,
    ) -> int:
        """写入片段。vectors 非空时直接复用已有向量，不再调用 Embedding。"""
        if not texts:
            return 0
        if vectors is None:
            from .vectorstore import get_embedding

            vectors = get_embedding().embed(texts)
        vecs = np.asarray(vectors, dtype=np.float32)

        rows = []
        for i, t in enumerate(texts):
            m = metas[i] if i < len(metas) else {}
            vec = vecs[i].reshape(-1)
            if vec.shape[0] != self.dim:
                raise ValueError(
                    f"向量维度不匹配：期望 {self.dim}，实际 {vec.shape[0]}"
                )
            rows.append(
                {
                    "id": (ids[i] if ids and i < len(ids) else None) or uuid.uuid4().hex,
                    "doc_id": str(m.get("doc_id", ""))[:MAX_STR_LEN],
                    "doc_name": str(m.get("doc_name", ""))[:MAX_STR_LEN],
                    "section": str(m.get("section", ""))[:MAX_STR_LEN],
                    "source": str(m.get("source", ""))[:MAX_STR_LEN],
                    "text": (t or "")[:MAX_TEXT_LEN],
                    "embedding": vec.astype(float).tolist(),
                }
            )
        for i in range(0, len(rows), 256):
            self.client.insert(collection_name=self.collection, data=rows[i : i + 256])
        self.client.flush(collection_name=self.collection)
        with self._lock:
            self._invalidate()
        return len(texts)

    def search(
        self,
        query_vec: np.ndarray,
        top_k: int = 4,
        query_text: str | None = None,
        doc_filter: str | None = None,
    ) -> list[Hit]:
        """混合检索：Milvus 向量召回 + BM25 关键词召回，融合后按文档章节去重。"""
        if self.count() == 0:
            return []

        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        if q.shape[0] != self.dim:
            raise ValueError(f"查询向量维度不匹配：期望 {self.dim}，实际 {q.shape[0]}")

        expr = f'doc_id == "{doc_filter}"' if doc_filter else ""
        n_probe = max(top_k * 5, 20)

        # 1) 向量召回
        vec_map: dict[str, float] = {}
        try:
            res = self.client.search(
                collection_name=self.collection,
                data=[q.astype(float).tolist()],
                limit=n_probe,
                filter=expr or "",
                output_fields=["id", "text", "doc_id", "doc_name", "section", "source"],
            )
            for group in res:
                for item in group:
                    vec_map[str(item.get("id"))] = float(item.get("distance", 0.0))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Milvus 向量检索失败：{e}")

        # 2) 关键词召回（BM25）
        kw_map: dict[str, float] = {}       # 归一化分（用于融合）
        kw_raw: dict[str, float] = {}       # 原始 BM25 分（用于相关性阈值判定）
        meta_map: dict[str, dict] = {}
        if query_text:
            self._ensure_bm25()
            bm25 = self._bm25
            if bm25 is not None and bm25.tf:
                kw = bm25.search(query_text)
                # 绝对尺度压缩到 0~1：保留区分度，避免相对归一化把噪声抬到满分
                kw_norm = kw / (kw + 8.0)
                order = np.argsort(-kw_norm)[: max(top_k * 5, 20)]
                snap = self._snapshot
                for i in order:
                    if kw[i] <= 0:
                        continue
                    _id = self._bm25_ids[i]
                    r = snap.get(_id)
                    if not r:
                        continue
                    if doc_filter and str(r.get("doc_id", "")) != doc_filter:
                        continue
                    kw_map[_id] = float(kw_norm[i])
                    kw_raw[_id] = float(kw[i])
                    meta_map[_id] = r

        # 3) 合并候选
        cand_ids = set(vec_map) | set(kw_map)
        if not cand_ids:
            return []

        # 3.1) 补算候选向量分。
        # Milvus 只返回向量 Top-N，纯靠 BM25 进池的候选没有向量分（=0.0）。
        # 这会在"按向量相似度判定"时留下空洞：实测"北京有哪些景点？"Top-1 是关键词
        # 命中的噪声段，向量分显示 0，看起来像是"语义最远"，实际只是没算。
        # 候选通常只有几十条，按 id 取回向量本地算余弦，代价远小于再检索一次。
        missing_vec = [i for i in cand_ids if i not in vec_map]
        if missing_vec:
            for start in range(0, len(missing_vec), 64):
                chunk = missing_vec[start : start + 64]
                try:
                    rows = self.client.query(
                        collection_name=self.collection,
                        filter='id in ["' + '","'.join(chunk) + '"]',
                        output_fields=["id", "embedding"],
                        limit=len(chunk),
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[warn] Milvus 补算向量分失败：{e}")
                    break
                for r in rows:
                    v = np.asarray(r.get("embedding") or [], dtype=np.float64).reshape(-1)
                    n = float(np.linalg.norm(v))
                    if n > 0 and v.shape[0] == q.shape[0]:
                        vec_map[str(r.get("id"))] = float(np.dot(v, q.astype(np.float64)) / n)
        missing = [i for i in cand_ids if i not in meta_map]
        if missing:
            rows = self.client.query(
                collection_name=self.collection,
                filter="",
                output_fields=["id", "text", "doc_id", "doc_name", "section", "source"],
                limit=16384,
            )
            for r in rows:
                meta_map[str(r.get("id"))] = r

        # 3.2) 融合：**信号弱的通道不参与排序**。
        # 口语化泛问（"我想开个小店，要办啥"）与政务术语字面几乎不重叠，BM25 只剩下
        # "办/要/啥"这类单二元组的噪声分（实测能给不相关文档打到 11 分）。若仍按
        # 0.55 的权重把它算进融合分，噪声文档会反超真正的语义命中 —— 实测 Top-1
        # 从《个体工商户设立登记》(向量 0.789) 被挤成《城乡居民养老保险参保登记》(0.575)，
        # 排序与判定一起被带偏。因此：只有问题里确实出现政务术语（关键词分够强）
        # 时才做混合，否则**纯按向量相似度排序**。
        kw_strong = bool(kw_raw) and max(kw_raw.values()) >= settings.KEYWORD_MIN_SCORE

        scored: list[tuple[str, float, float, float]] = []
        for _id in cand_ids:
            r = meta_map.get(_id)
            if not r:
                continue
            if doc_filter and str(r.get("doc_id", "")) != doc_filter:
                continue
            vs = vec_map.get(_id, 0.0)
            kn = kw_map.get(_id, 0.0)
            fused = 0.45 * vs + 0.55 * kn if kw_strong else vs
            scored.append((_id, fused, vs, kw_raw.get(_id, 0.0)))
        scored.sort(key=lambda x: -x[1])

        seen: set[tuple[str, str]] = set()
        hits: list[Hit] = []
        for _id, fused, vs, kn in scored:
            r = meta_map[_id]
            key = (str(r.get("doc_id", "")), str(r.get("section", "")))
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                Hit(
                    text=str(r.get("text", "")),
                    doc_id=str(r.get("doc_id", "")),
                    doc_name=str(r.get("doc_name", "")),
                    section=str(r.get("section", "")),
                    score=float(fused),
                    meta={
                        "doc_id": str(r.get("doc_id", "")),
                        "doc_name": str(r.get("doc_name", "")),
                        "section": str(r.get("section", "")),
                        "source": str(r.get("source", "")),
                    },
                    vector_score=float(vs),
                    keyword_score=float(kn),
                )
            )
            if len(hits) >= max(top_k, 1):
                break
        return hits

    def fetch_doc(self, doc_id: str, limit: int = 50) -> list[Hit]:
        """取某篇文档的片段（按 chunk_index 排序），供工作台的切分预览使用。

        chunk_index 不在建表 schema 里，但集合开了 enable_dynamic_field，
        所以能直接查出来；查不到就当 0，退化为按返回顺序展示。
        """
        d = str(doc_id).replace('"', '\\"')
        try:
            rows = self.client.query(
                collection_name=self.collection,
                filter=f'doc_id == "{d}"',
                output_fields=["text", "doc_id", "doc_name", "section", "chunk_index"],
                limit=max(int(limit), 1),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Milvus 取文档片段失败：{e}")
            return []

        def _idx(r) -> int:
            try:
                return int(r.get("chunk_index", 0) or 0)
            except (TypeError, ValueError):
                return 0

        rows = sorted(rows, key=_idx)
        return [
            Hit(
                text=str(r.get("text", "")),
                doc_id=str(r.get("doc_id", "")),
                doc_name=str(r.get("doc_name", "")),
                section=str(r.get("section", "")),
                meta={
                    "doc_id": str(r.get("doc_id", "")),
                    "doc_name": str(r.get("doc_name", "")),
                    "section": str(r.get("section", "")),
                    "chunk_index": _idx(r),
                },
            )
            for r in rows
        ]

    def fetch_section(self, doc_id: str, section: str, limit: int = 64) -> list[Hit]:
        """见基类说明：绕开 search() 的 (doc_id, section) 去重，取同章节全部片段。"""
        if not doc_id or not section:
            return []
        # doc_id / section 都来自我们自己的入库数据，不含引号；这里仍做一次转义兜底
        d = str(doc_id).replace('"', '\\"')
        s = str(section).replace('"', '\\"')
        try:
            rows = self.client.query(
                collection_name=self.collection,
                filter=f'doc_id == "{d}" and section == "{s}"',
                output_fields=["id", "text", "doc_id", "doc_name", "section", "source"],
                limit=int(limit),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Milvus 章节取片段失败：{e}")
            return []
        return [
            Hit(
                text=str(r.get("text", "")),
                doc_id=str(r.get("doc_id", "")),
                doc_name=str(r.get("doc_name", "")),
                section=str(r.get("section", "")),
                score=0.0,
                meta={
                    "doc_id": str(r.get("doc_id", "")),
                    "doc_name": str(r.get("doc_name", "")),
                    "section": str(r.get("section", "")),
                    "source": str(r.get("source", "")),
                },
            )
            for r in rows
        ]

    def count(self) -> int:
        try:
            st = self.client.get_collection_stats(self.collection)
            return int(st.get("row_count", 0) or 0)
        except Exception:  # noqa: BLE001
            return 0

    def clear(self) -> None:
        if self.client.has_collection(self.collection):
            self.client.drop_collection(self.collection)
        self._ensure_collection()
        with self._lock:
            self._invalidate()

    def delete_by_doc_id(self, doc_id: str) -> int:
        """按 doc_id 删除片段。

        先查出命中条数再删：pymilvus 各版本 delete() 的返回值不统一（有的没有
        delete_count），直接取返回值会在部分版本上拿到 0，前端就以为"没删掉"。
        """
        # doc_id 由我们生成（uuid5 十六进制），不含引号；仍转义兜底，防止 filter 注入
        d = str(doc_id).replace('"', '\\"')
        expr = f'doc_id == "{d}"'
        try:
            rows = self.client.query(
                collection_name=self.collection,
                filter=expr,
                output_fields=["id"],
                limit=16384,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Milvus 统计待删除片段失败：{e}")
            return 0
        if not rows:
            return 0
        try:
            self.client.delete(collection_name=self.collection, filter=expr)
            self.client.flush(collection_name=self.collection)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Milvus 删除片段失败：{e}")
            return 0
        with self._lock:
            self._invalidate()   # 删完必须重建 BM25 镜像，否则关键词检索仍命中已删文本
        return len(rows)

    def doc_stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        try:
            for r in self._iter_rows(["doc_id"]):
                d = str(r.get("doc_id", ""))
                out[d] = out.get(d, 0) + 1
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Milvus 统计文档片段数失败：{e}")
        return out
