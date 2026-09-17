"""知识库离线预处理：文档加载 -> 文本清洗 -> 分块 -> 向量化入库。"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..database import SessionLocal
from ..models import DocMeta
from ..utils.text import chunk_text, clean_text, split_sections
from .vectorstore import get_vector_store

SUPPORTED = {".txt", ".md", ".markdown", ".pdf", ".docx"}


# ---------------- 文档加载 ----------------
def load_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    if suffix == ".docx":
        import docx

        d = docx.Document(str(path))
        return "\n".join(p.text for p in d.paragraphs)
    raise ValueError(f"不支持的文档类型：{suffix}")


# ---------------- 切分 ----------------
# 多数政务文档里"实施依据"没有独立的标题行，只有"依据文号/法律法规名称"这类表格列名，
# 于是它会被上一个可识别章节（材料清单、收费标准）整个吞掉 —— 实测 GD08 的"收费标准"
# 因此吞了 32,769 字、GD01 的"材料清单"吞了 14,152 字，里面装的全是法规条款。
# 后果是 rerank 的"依据类降权"完全失效（它按 section 名判定），法规条款反而排到前面。
_BASIS_MARKERS = ("依据文号", "法律法规名称", "条款号", "颁布机关")
_BASIS_SECTIONS = ("实施依据", "设定依据", "法律依据", "政策依据")


def _true_section(section: str, chunk: str) -> str:
    """按内容校正章节名：含法规字段的片段一律归到"实施依据"。"""
    if section in _BASIS_SECTIONS:
        return section
    if sum(1 for m in _BASIS_MARKERS if m in chunk) >= 2:
        return "实施依据"
    return section


def build_chunks(text: str, doc_title: str = "") -> list[tuple[str, str]]:
    """先按章节切分，再对长章节做重叠窗口切分。返回 [(section, chunk)]。

    每个文本块前追加"文档标题 + 章节标题"作为上下文头（contextual chunk headers），
    显著提升"社保卡需要什么材料"这类跨章节问题的召回准确率。
    """
    out: list[tuple[str, str]] = []
    for section, body in split_sections(text):
        for c in chunk_text(body, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP):
            sec = _true_section(section, c)
            header = "\n".join(x for x in (doc_title, sec) if x)
            out.append((sec, f"{header}\n{c}" if header else c))
    return out


def _chunk_with_pipeline(text: str, doc_title: str) -> list[tuple[str, str]]:
    """按 PIPELINE 配置选择切分实现（langchain 走 LangChain TextSplitter）。"""
    if (settings.PIPELINE or "native").lower() == "langchain":
        try:
            from .langchain_pipeline import build_chunks as lc_build_chunks

            return lc_build_chunks(text, doc_title=doc_title)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] LangChain 切分失败，回退原生实现：{e}")
    return build_chunks(text, doc_title=doc_title)


_FNAME_PREFIX = re.compile(r"^[A-Za-z]{0,3}\d+[a-z]?[-_]")
_FNAME_SUFFIX = re.compile(r"[-_]广东政务网$")


def _title_from_filename(path: Path) -> str:
    """文件名往往比正文首行更可靠。

    GD03b（居住证签注）的正文首行是"申领居住证" —— PDF 页眉串了，
    与 GD03 完全同名，两篇文档在库里都叫"申领居住证"，
    导致"第一次申领"和"到期续期"这两件事根本无法区分。
    文件名是人工整理过的，天然唯一，优先用它。
    """
    stem = _FNAME_SUFFIX.sub("", path.stem)
    stem = _FNAME_PREFIX.sub("", stem).strip("_-— ")
    # 文件名没有语义时（doc1.pdf 之类）仍退回正文首行
    return stem if len(stem) >= 4 and re.search(r"[\u4e00-\u9fff]", stem) else ""


# PDF 首页的页眉常常是"指南地址:https://www.gdzwfw.gov.cn/..."这类 URL。
# 文件名没有语义时（用户上传的 PDF 常叫 qz.pdf / 文档1.pdf）就会拿它当文档名，
# 列表里显示成一长串网址 —— 既难看又没法认。这些行一律跳过。
_URL_HEADER = re.compile(r"^(https?://|www\.|指南地址|网址|来源\s*[:：]|页码)", re.I)


def extract_title(text: str, path: Path, override: str = "") -> str:
    """文档名优先级：调用方指定 > 文件名 > 正文首个有效行 > 文件名 stem。"""
    if override and override.strip():
        return override.strip()[:120]
    fname = _title_from_filename(path)
    if fname:
        return fname[:120]
    for line in text.split("\n")[:8]:
        line = line.strip().lstrip("#").strip()
        if not line or _URL_HEADER.match(line):
            continue
        return line[:120]
    return path.stem


# ---------------- 入库 ----------------
def _delete_existing(doc_id: str) -> int:
    """写入前清掉同一 doc_id 的旧片段，返回清除条数。

    doc_id 由文件名决定，所以"重新导入一篇语料"必然落到同一个 doc_id 上。
    旧实现只管 add —— 同一篇文档灌两次，库里就会留两份一模一样的片段：
    检索时它们互相占位（Top-K 被重复片段挤满），"删除语料"也只能删掉其中一批。
    """
    try:
        return int(get_vector_store().delete_by_doc_id(doc_id))
    except NotImplementedError:
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 清理旧片段失败（doc_id={doc_id}）：{e}")
        return 0


def ingest_file(path: Path, clear: bool = False, title: str = "") -> dict:
    """处理单个文档并写入向量库 + doc_meta 表。

    title：调用方指定的文档名（工作台上传时用户填的），留空则按文件名/正文推断。
    """
    store = get_vector_store()
    if clear:
        store.clear()

    raw = load_text(path)
    text = clean_text(raw)
    if not text.strip():
        return {"doc": path.name, "chunks": 0, "status": "empty"}

    doc_name = extract_title(text, path, override=title)
    doc_id = uuid.uuid5(uuid.NAMESPACE_URL, f"gov-doc:{path.name}").hex[:16]

    pairs = _chunk_with_pipeline(text, doc_name)
    if not pairs:
        return {"doc": path.name, "chunks": 0, "status": "empty"}

    _delete_existing(doc_id)

    texts, metas = [], []
    for i, (section, chunk) in enumerate(pairs):
        texts.append(chunk)
        metas.append(
            {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "section": section,
                "chunk_index": i,
                "source": path.name,
            }
        )

    store.add(texts, metas, ids=[f"{doc_id}_{i}" for i in range(len(texts))])

    # 文档基础信息写入 MySQL / SQLite
    db = SessionLocal()
    try:
        existing = db.get(DocMeta, doc_id)
        if existing:
            existing.doc_name = doc_name
            existing.source = path.name
            existing.upload_time = datetime.now()
        else:
            db.add(
                DocMeta(
                    doc_id=doc_id,
                    doc_name=doc_name,
                    source=path.name,
                    upload_time=datetime.now(),
                )
            )
        db.commit()
    finally:
        db.close()

    return {
        "doc": doc_name,
        "doc_id": doc_id,
        "source": path.name,
        "chunks": len(texts),
        "status": "ok",
    }


def ingest_dir(directory: Path | None = None, clear: bool = False) -> dict:
    """批量导入目录下所有支持格式的文档。"""
    directory = Path(directory) if directory else settings.docs_dir
    if not directory.exists():
        return {"total": 0, "chunks": 0, "details": [], "error": f"目录不存在：{directory}"}

    store = get_vector_store()
    if clear:
        store.clear()

    files = sorted(p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
    details, total_chunks = [], 0
    for f in files:
        try:
            r = ingest_file(f)
            details.append(r)
            total_chunks += r["chunks"]
        except Exception as e:  # noqa: BLE001
            details.append({"doc": f.name, "chunks": 0, "status": f"failed: {e}"})

    return {"total": len(files), "chunks": total_chunks, "details": details}
