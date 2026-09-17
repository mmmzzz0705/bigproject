"""启动前依赖自检：一次看清 PostgreSQL / Milvus / Embedding / 大模型 是否可用。

用法：
    python scripts/check_env.py              # 全部检查
    python scripts/check_env.py --skip-llm   # 跳过大模型（省钱省时间）

退出码：全部通过返回 0，任一失败返回 1。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

OK = "PASS"
NG = "FAIL"
SKIP = "SKIP"

_results: list[tuple[str, str, str, float]] = []


def record(name: str, status: str, detail: str = "", cost: float = 0.0) -> None:
    _results.append((name, status, detail, cost))
    print(f"  [{status}] {name:<10} {detail}" + (f"  ({cost:.2f}s)" if cost else ""))


# 本项目依赖 pymilvus / chromadb / pydantic-core 等含预编译二进制的包。
# 3.14 上这些包大多没有 cp314 wheel，会走源码构建并大概率装坏
# （实测 pymilvus 报 `cannot import name 'rg_pb2'`，
#   pydantic-core 报 `No module named 'pydantic_core._pydantic_core'`）。
MAX_TESTED_MINOR = 13


def check_python() -> None:
    """解释器版本与「venv 是否被换过 Python」自检。

    第二项容易被忽略：`python -m venv` 作用在已存在的 .venv 上**不会清空**
    site-packages，于是旧版本的 .pyd 留在原地，新解释器加载不了。
    症状是 ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'。
    这里直接比对 venv 版本与 site-packages 里 .pyd 的 cp3XX 后缀。
    """
    import platform
    import sysconfig
    from pathlib import Path

    v = sys.version_info
    ver = platform.python_version()
    venv_root = Path(sysconfig.get_paths()["purelib"]).parent.parent
    cfg = venv_root / "pyvenv.cfg"
    print("\n[0/5] 解释器")
    print(f"      版本         : {ver}")
    print(f"      路径         : {sys.executable}")
    print(f"      虚拟环境     : {'是' if sys.prefix != sys.base_prefix else '否（直接用了系统 Python）'}")

    if (v.major, v.minor) > (3, MAX_TESTED_MINOR):
        print(f"      [WARN] 未在 {ver} 上验证过；建议用 3.12 / 3.13，否则部分依赖可能装不上")
        _results.append(("python", NG, f"{ver} 未验证（建议 3.12/3.13）", 0.0))
    else:
        _results.append(("python", OK, ver, 0.0))

    # venv 被换过 Python：pyvenv.cfg 的版本 与 .pyd 的 cp3XX 后缀对不上
    tag = f"cp{v.major}{v.minor}"
    pyds = list(Path(sysconfig.get_paths()["purelib"]).glob("pydantic_core/_pydantic_core.cp3*.pyd"))
    if pyds:
        # 文件名形如 _pydantic_core.cp312-win_amd64.pyd -> 取 "cp312"
        suffixes = {p.name.split(".")[1].split("-")[0] for p in pyds}
        if tag not in suffixes:
            print(f"      [FAIL] site-packages 里是 {sorted(suffixes)}，当前解释器是 {tag}")
            print("             —— 典型的「venv 被换过 Python 但没清空」。")
            print("             修：删掉 .venv 再重建（rmdir /s /q .venv）。")
            _results.append(("venv-abi", NG, f"残留 {sorted(suffixes)}，期望 {tag}", 0.0))
        else:
            _results.append(("venv-abi", OK, tag, 0.0))
    if cfg.exists():
        print(f"      pyvenv.cfg   : {cfg}")


def check_config() -> None:
    print("\n[1/5] 配置")
    print(f"      数据库       : {settings.db_type}  {settings.DB_HOST}:{settings.db_port}/{settings.DB_NAME}")
    print(f"      向量库       : {settings.VECTOR_STORE}  dim={settings.VECTOR_DIM}")
    print(f"      Embedding    : {settings.EMBEDDING_PROVIDER} / {settings.DASHSCOPE_EMBED_MODEL}")
    print(f"      大模型       : {settings.LLM_PROVIDER} / {settings.DASHSCOPE_MODEL}")
    print(f"      闸门阈值     : 向量>={settings.VECTOR_MIN_SCORE}  关键词>={settings.KEYWORD_MIN_SCORE}")


def check_database() -> None:
    print("\n[2/5] 关系数据库")
    t0 = time.time()
    try:
        from app.database import ACTIVE_DB_TYPE, engine
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        label = {"postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite"}.get(
            ACTIVE_DB_TYPE, ACTIVE_DB_TYPE
        )
        extra = ""
        if ACTIVE_DB_TYPE == settings.db_type:
            with engine.connect() as conn:
                n = conn.execute(text("SELECT COUNT(*) FROM doc_meta")).scalar()
                s = conn.execute(text("SELECT COUNT(*) FROM session")).scalar()
                h = conn.execute(text("SELECT COUNT(*) FROM chat_history")).scalar()
                extra = f"doc_meta={n} session={s} chat_history={h}"
        record("database", OK, f"{label} 连通  {extra}", time.time() - t0)
    except Exception as exc:
        record("database", NG, f"连接失败：{exc}", time.time() - t0)


def check_vector_store() -> None:
    print("\n[3/5] 向量库")
    t0 = time.time()
    try:
        from app.services.vectorstore import get_vector_store

        store = get_vector_store()
        n = store.count()
        status = OK if n > 0 else NG
        note = "" if n > 0 else "  <- 知识库为空，需执行导入脚本"
        record("vector", status, f"{store.name}  {n} 个片段{note}", time.time() - t0)
    except Exception as exc:
        record("vector", NG, f"连接失败：{exc}", time.time() - t0)


def check_embedding() -> None:
    print("\n[4/5] Embedding")
    t0 = time.time()
    try:
        from app.services.embeddings import build_embedding

        emb = build_embedding()
        vec = emb.embed(["个体工商户设立登记"])
        dim = len(vec[0])
        status = OK if dim == settings.VECTOR_DIM else NG
        note = "" if dim == settings.VECTOR_DIM else f"  <- 与 VECTOR_DIM={settings.VECTOR_DIM} 不一致，检索会失败"
        record("embedding", status, f"{emb.name}  dim={dim}{note}", time.time() - t0)
    except Exception as exc:
        record("embedding", NG, f"调用失败：{exc}", time.time() - t0)


def check_llm(skip: bool) -> None:
    print("\n[5/5] 大模型")
    if skip:
        record("llm", SKIP, "已跳过（--skip-llm）")
        return
    t0 = time.time()
    try:
        from app.services.llm import build_llm

        llm = build_llm()
        out = llm.generate("只回复两个字：你好")
        text = (out or "").strip()
        status = OK if text and not text.startswith("{") else NG
        record("llm", status, f"{getattr(llm, 'name', '?')}  ->  {text[:40]!r}", time.time() - t0)
    except Exception as exc:
        record("llm", NG, f"调用失败：{exc}", time.time() - t0)


def main() -> int:
    parser = argparse.ArgumentParser(description="政务问答系统依赖自检")
    parser.add_argument("--skip-llm", action="store_true", help="跳过大模型调用")
    args = parser.parse_args()

    print("=" * 60)
    print(" 政务问答系统 - 依赖自检")
    print("=" * 60)

    check_python()
    check_config()
    check_database()
    check_vector_store()
    check_embedding()
    check_llm(args.skip_llm)

    print("\n" + "=" * 60)
    failed = [r for r in _results if r[1] == NG]
    passed = [r for r in _results if r[1] == OK]
    print(f" 结果：{len(passed)} 项通过，{len(failed)} 项失败")
    if failed:
        print("\n 失败项：")
        for name, _, detail, _ in failed:
            print(f"   - {name}: {detail}")
        print("\n 提示：组件缺失不会阻止启动，系统会自动降级")
        print("       （关系库->SQLite，向量库->内存，大模型->抽取式）")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
