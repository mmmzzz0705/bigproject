# -*- coding: utf-8 -*-
"""把已有 RAG 管道产出的「片段 + 预计算向量」一次性导入本系统。

数据源：D:\\document\\rag_pipeline\\05_vectorstore\\index.json
    {model, dim, count, items: [{id, text, embedding, metadata:{doc_id, chunk_index, char_len}}]}

特点：
1. **复用已有向量**（不重复调用 Embedding 接口）；维度需与 `VECTOR_DIM` 一致；
2. 自动识别并归一化章节标题（基础信息 / 材料清单 / 办理流程 ...）；
3. 为每个片段追加「文档标题 + 章节」上下文头，提升跨章节问题召回；
4. 同步写入 PostgreSQL 的 doc_meta 表。

用法：
    python scripts/import_existing_vectors.py                 # 全量导入（追加）
    python scripts/import_existing_vectors.py --reset         # 先清空向量库再导入
    python scripts/import_existing_vectors.py --source <path> # 指定 index.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import DocMeta  # noqa: E402
from app.services.vectorstore import get_vector_store  # noqa: E402

DEFAULT_SOURCE = r"D:\document\rag_pipeline\05_vectorstore\index.json"
SOURCE_HINT = "广东政务服务网"

# 章节标题词表（独立成行即命中，取片段内最后一个）
# 注意：政务网页导出的 PDF 里，"材料名称/材料依据/材料形式/材料要求/材料下载/其他信息"
# 是**表格列名**而非章节名，必须排除，否则会把材料表误判成"其他信息"。
SECTION_VOCAB = (
    "基础信息",
    "审批信息",
    "受理条件",
    "受理范围",
    "办理条件",
    "办理流程",
    "网上办理流程",
    "线下办理流程",
    "材料清单",
    "实施依据",
    "设定依据",
    "收费项目信息",
    "收费标准",
    "收费信息",
    "咨询方式与监督方式",
    "咨询方式",
    "办理地点",
    "注意事项",
)

# 标题归一化
SECTION_ALIAS = {
    "收费项目信息": "收费信息",
    "收费标准": "收费信息",
    "咨询方式与监督方式": "咨询方式",
}

_SECTION_RE = re.compile(r"^\s*(" + "|".join(SECTION_VOCAB) + r")\s*$")

# 正文特征词 -> 章节（权重 2 表示强特征）。用于对标题误判做内容级纠正：
# PDF 抽取常出现"导航块"（多个标题连续成行）与"标题缺失"，纯靠标题不可靠。
SECTION_HINTS: dict[str, tuple[tuple[str, int], ...]] = {
    "材料清单": (
        ("原件", 2), ("复印件", 2), ("纸质", 1), ("电子化", 1),
        ("免提交", 2), ("空白表格", 2), ("示例样本", 2), ("材料类型", 2),
        ("材料形式", 1), ("填报须知", 1), ("来源渠道", 1),
    ),
    "实施依据": (
        ("法律法规名称", 3), ("依据文号", 3), ("条款号", 3), ("颁布机关", 3),
        ("实施日期", 2), ("条款内容", 2), ("设定依据", 2),
    ),
    "办理流程": (
        ("网上办理流程", 2), ("线下办理流程", 2), ("窗口办理", 2), ("网上办理", 1),
        ("现场办理", 1), ("受理", 1), ("审查", 1), ("决定", 1),
    ),
    "收费信息": (
        ("收费项目信息", 3), ("不收费", 3), ("收费标准", 3), ("收费依据", 2), ("元/", 2),
    ),
    "咨询方式": (
        ("咨询方式与监督方式", 3), ("咨询方式", 2), ("监督方式", 2),
        ("投诉", 1), ("办理地点：", 2),
    ),
    "受理条件": (("受理条件", 2), ("申请条件", 2), ("符合下列", 2), ("受理范围", 2)),
    "基础信息": (
        ("事项名称", 3), ("事项类型", 2), ("承诺办结时限", 3), ("法定办结时限", 2),
        ("实施主体", 2), ("日常用语", 2), ("到办事现场次数", 2),
    ),
    "审批信息": (
        ("行使层级", 3), ("权力来源", 2), ("审批服务形式", 2), ("联办机构", 2),
        ("业务系统", 1), ("委托部门", 1),
    ),
}

HINT_THRESHOLD = 6


def derive_doc_name(doc_id: str) -> str:
    """GD01_个体工商户设立登记_广东政务网 -> 个体工商户设立登记"""
    name = re.sub(r"^GD\d+[a-zA-Z]?_", "", doc_id)
    name = re.sub(r"_广东政务网$", "", name)
    name = name.replace("_", " ").strip()
    return name or doc_id


def normalize_section(sec: str) -> str:
    return SECTION_ALIAS.get(sec, sec)


def detect_section(text: str) -> str | None:
    """在片段中查找章节标题（独立成行），取最后一个。"""
    found = None
    for line in text.split("\n"):
        s = line.strip()
        if not s or len(s) > 20:
            continue
        m = _SECTION_RE.match(s)
        if m:
            found = m.group(1)
    return normalize_section(found) if found else None


def hint_section(text: str) -> tuple[str, int] | None:
    """按正文特征词推断章节，返回 (章节, 得分)；低于阈值时返回 None。"""
    best, best_score = None, 0
    for sec, hints in SECTION_HINTS.items():
        score = sum(w for kw, w in hints if kw in text)
        if score > best_score:
            best, best_score = sec, score
    return (best, best_score) if best and best_score >= HINT_THRESHOLD else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="index.json 路径")
    ap.add_argument("--reset", action="store_true", help="导入前清空向量库")
    ap.add_argument(
        "--exclude",
        default="GD00",
        help="逗号分隔的 doc_id 前缀，跳过（默认跳过 GD00 索引清单，"
        "它是管道生成的文件目录，会把各类问题都吸引到同一篇上）",
    )
    ap.add_argument("--batch", type=int, default=128, help="每批写入条数")
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        print(f"[error] 数据源不存在：{src}")
        return 1

    print(f"[info] DB  = {settings.db_url.split('@')[-1]} ({settings.db_type})")
    print(f"[info] VEC = {settings.VECTOR_STORE} dim={settings.VECTOR_DIM}")

    data = json.load(io.open(src, encoding="utf-8"))
    items = data.get("items", [])
    dim = int(data.get("dim") or 0)
    if not items:
        print("[error] 数据源为空")
        return 1
    if dim != settings.VECTOR_DIM:
        print(
            f"[error] 向量维度不一致：源 {dim} != 配置 VECTOR_DIM {settings.VECTOR_DIM}\n"
            f"        请在 .env 中设置 VECTOR_DIM={dim}"
        )
        return 1

    excludes = tuple(x.strip() for x in args.exclude.split(",") if x.strip())

    init_db()
    store = get_vector_store()
    print(f"[info] 向量库 = {store.name}")
    if args.reset:
        store.clear()
        print("[info] 已清空向量库")

    # 按 doc_id 聚合，保持章节继承
    by_doc: "OrderedDict[str, list[dict]]" = OrderedDict()
    for it in items:
        did = it.get("metadata", {}).get("doc_id", "")
        if excludes and did.startswith(excludes):
            continue
        by_doc.setdefault(did, []).append(it)

    db = SessionLocal()
    total = 0
    try:
        for doc_id, chunks in by_doc.items():
            chunks.sort(key=lambda x: x.get("metadata", {}).get("chunk_index", 0))
            doc_name = derive_doc_name(doc_id)
            section = "正文"

            texts, metas, ids, vecs = [], [], [], []
            for it in chunks:
                body = it.get("text", "") or ""
                sec = detect_section(body)
                if sec:
                    section = sec
                # 内容级纠正：标题被导航块/表格列名污染时，以正文特征为准
                hinted = hint_section(body)
                if hinted:
                    section = hinted[0]
                header = f"{doc_name}\n{section}\n"
                texts.append(header + body)
                metas.append(
                    {
                        "doc_id": doc_id,
                        "doc_name": doc_name,
                        "section": section,
                        "chunk_index": it.get("metadata", {}).get("chunk_index", 0),
                        "source": SOURCE_HINT,
                    }
                )
                ids.append(str(it.get("id"))[:120])
                vecs.append(it.get("embedding"))

            written = 0
            for i in range(0, len(texts), args.batch):
                written += store.add(
                    texts[i : i + args.batch],
                    metas[i : i + args.batch],
                    ids=ids[i : i + args.batch],
                    vectors=vecs[i : i + args.batch],
                )
            total += written

            row = db.get(DocMeta, doc_id)
            if row:
                row.doc_name = doc_name
                row.source = SOURCE_HINT
                row.upload_time = datetime.now()
            else:
                db.add(
                    DocMeta(
                        doc_id=doc_id,
                        doc_name=doc_name,
                        source=SOURCE_HINT,
                        upload_time=datetime.now(),
                    )
                )
            db.commit()
            print(f"  · {doc_name}  ({written} 块)")

        print(f"\n[ok] 导入完成：{len(by_doc)} 篇文档 / {total} 个片段 -> {store.name}")
        print(f"[ok] 向量库当前总数：{store.count()}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
