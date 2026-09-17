"""离线文档预处理脚本（由开发人员执行，非 Web 接口）。

用法：
    python scripts/ingest.py                       # 导入 data/docs 下所有文档
    python scripts/ingest.py --dir D:/政策文件      # 指定目录
    python scripts/ingest.py --file a.pdf          # 导入单个文件
    python scripts/ingest.py --clear               # 先清空向量库再导入
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.database import init_db  # noqa: E402
from app.services.ingest import ingest_dir, ingest_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="政务知识库离线预处理")
    parser.add_argument("--dir", default=str(settings.docs_dir), help="文档目录")
    parser.add_argument("--file", default="", help="单个文档路径（优先于 --dir）")
    parser.add_argument("--clear", action="store_true", help="导入前清空向量库")
    args = parser.parse_args()

    init_db()
    print(f"[config] vector_store={settings.VECTOR_STORE} embedding={settings.EMBEDDING_PROVIDER}")

    if args.file:
        r = ingest_file(Path(args.file), clear=args.clear)
        print(f"[done] {r}")
        return

    r = ingest_dir(Path(args.dir), clear=args.clear)
    print(f"[done] 文档数={r['total']} 文本块={r['chunks']}")
    for d in r.get("details", []):
        print(f"  - {d['doc']}: {d['chunks']} chunks [{d['status']}]")


if __name__ == "__main__":
    main()
