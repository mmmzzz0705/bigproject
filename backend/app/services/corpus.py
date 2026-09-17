"""工作台语料管理：上传 / 粘贴 / 列表 / 删除 / 重新导入。

职责边界
--------
- ``ingest.py`` 负责离线预处理（加载文件 → 清洗 → 切块 → 向量化入库）。本模块不复制它的
  逻辑，只调用 ``ingest_file`` —— 切块口径只有一处，工作台与离线脚本永远一致。
- 本模块负责一篇语料**在线进出的完整生命周期**：校验上传内容 → 落盘 → 入库 →
  同步 doc_meta → 删除时清理向量与磁盘文件。
- 路由层只做参数校验与错误码映射，不放业务逻辑（便于单测直接打这一层）。

语料归属（origin）如何判定
--------------------------
没有给 doc_meta 加 origin 列（那要给 PostgreSQL 和 SQLite 各写一遍迁移），而是按
"文件当前在哪个目录"实时判定：uploads 目录 = 用户上传（可删文件），
docs_dir = 内置基准语料（只读挂载，删不掉也不该删），两边都没有 = 文件已丢失。
文件位置本来就是归属的事实来源 —— 删除时要按它决定"能不能删磁盘文件"，
判定口径与删除行为天然一致，不存在元数据与文件打架的情况。
"""
from __future__ import annotations

import re
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import DocMeta
from .ingest import SUPPORTED, ingest_file
from .vectorstore import get_vector_store

ORIGIN_UPLOADED = "uploaded"
ORIGIN_BUILTIN = "builtin"
ORIGIN_MISSING = "missing"

# 落盘文件名白名单：中英文、数字、下划线、连字符、点，其余一律换成 _
_UNSAFE = re.compile(r"[^\w\u4e00-\u9fff.-]+")
_TEXT_SUFFIX = re.compile(r"\.(txt|md|markdown|pdf|docx)$", re.I)

# 语料写操作串行化。
# "更新语料"是先清旧片段再写入，中间有几十秒的 Embedding 调用窗口；
# 如果这期间另一个请求来删同一篇（或再传一版），两边交错就会留下半新半旧的片段，
# 而且很难复现。管理台并发极低，串行化的代价（多等一会儿）远小于数据错乱的代价。
_WRITE_LOCK = threading.Lock()


# ---------------- 文件名与落盘 ----------------
def safe_filename(name: str, fallback: str = "upload") -> str:
    """把上传文件名收敛成安全的落盘名。

    三件事必须做全，少一件就是漏洞：
    1. 只取 ``Path(...).name`` —— 去掉 ``../../`` 这类目录前缀，防路径穿越；
    2. NFKC 归一化 + 去控制字符 —— 防同名混淆与不可见字符；
    3. 保留扩展名 —— 入库时按扩展名选解析器（pdf / docx / txt）。
    中文必须保留：政务文件名几乎全是中文，抹掉就无法辨认。
    """
    raw = Path(unicodedata.normalize("NFKC", name or "")).name
    suffix = Path(raw).suffix.lower()
    stem = _UNSAFE.sub("_", Path(raw).stem).strip("._")[:80] or fallback
    return f"{stem}{suffix}"


def _avoid_builtin_clash(name: str) -> str:
    """上传文件不能与内置语料同名。

    doc_id 由文件名哈希而来，一旦同名就是同一个 doc_id —— 入库会**覆盖掉内置基准语料的
    全部片段**，而且删的时候元数据一起删，内置语料从此无法 reingest（源文件还在，但
    记录没了）。所以落盘前先改名，宁可名字丑一点，也不能让基准语料被悄悄顶掉。
    """
    if not (settings.docs_dir / name).exists():
        return name
    p = Path(name)
    for i in range(1, 100):
        cand = f"{p.stem}_上传{'' if i == 1 else i}{p.suffix}"
        if not (settings.docs_dir / cand).exists():
            return cand
    return f"{p.stem}_上传{uuid.uuid4().hex[:6]}{p.suffix}"


def _text_filename(title: str) -> str:
    """由标题生成落盘名（统一 .txt，避免标题自带扩展名变成 xxx.txt.txt）。"""
    base = safe_filename(_TEXT_SUFFIX.sub("", title).strip(), fallback="text")
    return f"{base}.txt"


def _origin_of(source: str) -> str:
    """按文件当前所在目录判定语料归属。"""
    name = Path(source or "").name
    if not name:
        return ORIGIN_MISSING
    if (settings.upload_dir / name).exists():
        return ORIGIN_UPLOADED
    if (settings.docs_dir / name).exists():
        return ORIGIN_BUILTIN
    return ORIGIN_MISSING


# ---------------- 添加 ----------------
def _ingest(path: Path, title: str = "") -> dict:
    """落盘后的统一入库动作；失败时由调用方清理文件。"""
    r = ingest_file(path, title=title)
    if r.get("status") != "ok" or not r.get("chunks"):
        raise ValueError(
            "未能从该文件解析出有效文本（空文件？扫描版 PDF 没有文字层？）"
        )
    return {
        "doc_id": r["doc_id"],
        "doc_name": r["doc"],
        "source": r["source"],
        "chunks": int(r["chunks"]),
        "status": "ok",
    }


def add_document(filename: str, data: bytes, title: str = "") -> dict:
    """上传文件入库。同名文件视为"更新"：先清旧片段再写入（见 ingest._delete_existing）。

    title 为空时按文件名推断文档名；文件名常常没有语义（qz.pdf、文档1.docx），
    此时调用方应让用户填一个，否则列表里会出现"指南地址:https://..."这类页眉。
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(
            f"不支持的文件类型：{suffix or '(无扩展名)'}，仅支持 {', '.join(sorted(SUPPORTED))}"
        )
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > limit:
        raise ValueError(
            f"文件 {len(data) / 1024 / 1024:.1f}MB 超过 {settings.MAX_UPLOAD_MB}MB 上限"
        )
    if not data.strip():
        raise ValueError("文件内容为空")

    path = settings.upload_dir / _avoid_builtin_clash(safe_filename(filename))
    # 同名 = 更新：旧片段会在入库前被清掉（见 ingest._delete_existing）。
    # 记下来，万一入库失败要明确告诉用户"旧的那篇已经没了"。
    is_update = path.exists()
    with _WRITE_LOCK:
        path.write_bytes(data)
        try:
            return _ingest(path, title=title)
        except Exception as e:
            # 落盘成功但入库失败时不能留着文件：它不在库里，界面上看不到，
            # 下次同名上传会被静默覆盖，用户再也查不到这次失败。
            path.unlink(missing_ok=True)
            if is_update:
                raise ValueError(
                    f"入库失败，同名语料的旧片段已被移除，请重新上传该文件：{e}"
                ) from e
            raise


def add_text(title: str, content: str) -> dict:
    """粘贴文本入库：落盘成 txt 后走与上传完全相同的入库路径。"""
    title = (title or "").strip()
    content = (content or "").strip()
    if len(title) < 2:
        raise ValueError("语料标题至少 2 个字符")
    if len(content) < 20:
        raise ValueError("正文太短（至少 20 字），切不出有效片段")
    if len(content) > settings.MAX_CORPUS_TEXT_CHARS:
        raise ValueError(f"正文 {len(content)} 字，超过 {settings.MAX_CORPUS_TEXT_CHARS} 字上限")

    path = settings.upload_dir / _avoid_builtin_clash(_text_filename(title))
    is_update = path.exists()
    with _WRITE_LOCK:
        # 首行写标题：ingest.extract_title 会优先用文件名，文件名没有语义时退回正文首行，
        # 这里补上标题，保证库里的文档名与用户填的一致。
        path.write_text(f"{title}\n\n{content}", encoding="utf-8")
        try:
            return _ingest(path)
        except Exception as e:
            path.unlink(missing_ok=True)
            if is_update:
                raise ValueError(
                    f"入库失败，同名语料的旧片段已被移除，请重新提交：{e}"
                ) from e
            raise


# ---------------- 查询 ----------------
def list_documents() -> dict:
    """文档元数据（doc_meta）与向量库实际片段数合并输出。

    两边都要看：doc_meta 有记录而向量库 0 片段 = 已被删除的内置语料（界面上要能看出来），
    只看一边会把"删了"显示成"还在"。
    """
    store = get_vector_store()
    try:
        stats = store.doc_stats()
    except NotImplementedError:
        stats = {}

    db = SessionLocal()
    try:
        rows = db.execute(select(DocMeta).order_by(DocMeta.upload_time.desc())).scalars().all()
        docs = []
        for r in rows:
            chunks = int(stats.get(r.doc_id, 0))
            origin = _origin_of(r.source)
            docs.append(
                {
                    "doc_id": r.doc_id,
                    "doc_name": r.doc_name,
                    "source": r.source or "",
                    "chunks": chunks,
                    "upload_time": str(r.upload_time or ""),
                    "origin": origin,
                    # 0 片段 = 已被移出检索库（内置语料删除后就是这个状态，仍可恢复）
                    "in_index": chunks > 0,
                    "can_reingest": origin == ORIGIN_BUILTIN,
                }
            )
    finally:
        db.close()

    # 片段总数用 doc_stats 汇总，不用 store.count()：
    # Milvus 的删除是逻辑删除，row_count 里仍算着已删未 compaction 的行，
    # 实测删完一篇（3 片段）后 count() 一点没降，界面上会显示"删了但片段数没变"。
    # doc_stats 走的是 query，会过滤掉已删实体，与用户感知一致。
    total_chunks = int(sum(stats.values())) if stats else int(store.count())
    return {
        "total": len(docs),
        "total_chunks": total_chunks,
        "vector_store": store.name,
        "degraded": bool(getattr(store, "degraded", False)),
        "docs": docs,
    }


def list_chunks(doc_id: str, limit: int = 50) -> dict:
    """取某篇语料被切成的片段，供工作台预览。

    存在的意义是"可观测"：切得碎不碎、材料表有没有被切断、章节名认对了没 ——
    这些决定了检索能不能命中，但平时完全看不见。能直接看到切分结果，
    调 CHUNK_SIZE / 章节切分规则时才不用靠猜。
    """
    db = SessionLocal()
    try:
        row = db.get(DocMeta, doc_id)
        if not row:
            raise KeyError(f"语料不存在：{doc_id}")
        name = row.doc_name
    finally:
        db.close()

    limit = max(1, min(int(limit or 50), 200))
    hits = get_vector_store().fetch_doc(doc_id, limit=limit)
    return {
        "doc_id": doc_id,
        "doc_name": name,
        "shown": len(hits),
        "chunks": [
            {
                "index": int(h.meta.get("chunk_index", i) or i),
                "section": h.section or "",
                "chars": len(h.text),
                "text": h.text,
            }
            for i, h in enumerate(hits)
        ],
    }


# ---------------- 删除 / 重新导入 ----------------
def _delete_vectors(doc_id: str) -> int:
    store = get_vector_store()
    try:
        return int(store.delete_by_doc_id(doc_id))
    except NotImplementedError as e:
        raise RuntimeError(f"当前向量库（{store.name}）不支持按文档删除") from e


def _remove_file_if_uploaded(source: str) -> bool:
    """只删上传目录里的文件，内置语料文件一律不动。

    内置语料目录在容器里是只读挂载，硬删只会得到 PermissionError；
    更重要的是它属于基准语料 —— 删掉向量还能重新导入，删掉文件就真没了。
    """
    name = Path(source or "").name
    if not name:
        return False
    path = settings.upload_dir / name
    if not path.exists():
        return False
    path.unlink(missing_ok=True)
    return True


def delete_document(doc_id: str) -> dict:
    """删除一篇语料 = 把它移出检索库（清向量），再按归属决定删不删文件与元数据。

    - 用户上传语料：文件与元数据一起删，删干净，不留垃圾；
    - 内置基准语料：**只清向量，保留文件与元数据**。元数据删掉就再也找不回来了 ——
      doc_id 是由文件名哈希出来的，反过来推不出文件名，重新导入将无从下手；
      保留一行 chunks=0 的记录，列表里还能显示"已移出知识库"并给一键恢复的入口。
    """
    db = SessionLocal()
    try:
        row = db.get(DocMeta, doc_id)
        if not row:
            raise KeyError(f"语料不存在：{doc_id}")

        name, source = row.doc_name, row.source
        with _WRITE_LOCK:
            removed = _delete_vectors(doc_id)
            if _origin_of(source) == ORIGIN_UPLOADED:
                file_removed = _remove_file_if_uploaded(source)
                db.delete(row)
                meta_removed = True
            else:
                file_removed = False
                meta_removed = False
            db.commit()
        return {
            "doc_id": doc_id,
            "doc_name": name,
            "removed_chunks": removed,
            "file_removed": file_removed,
            "meta_removed": meta_removed,
            # 源文件还在内置目录 = 随时可以重新导入
            "recoverable": not meta_removed and _origin_of(source) == ORIGIN_BUILTIN,
            "status": "ok",
        }
    finally:
        db.close()


def reingest_document(doc_id: str) -> dict:
    """重新导入内置语料（删除后用它恢复）。"""
    db = SessionLocal()
    try:
        row = db.get(DocMeta, doc_id)
        if not row:
            raise KeyError(f"语料不存在：{doc_id}")
        src = settings.docs_dir / Path(row.source or "").name
        if not src.exists():
            raise FileNotFoundError(f"源文件已不在内置语料目录：{row.source}")

        with _WRITE_LOCK:
            r = _ingest(src)
            row.doc_name = r["doc_name"]
            row.upload_time = datetime.now()
            db.commit()
        return r
    finally:
        db.close()
