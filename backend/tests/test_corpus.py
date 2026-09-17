"""工作台语料管理测试（上传 / 粘贴 / 列表 / 删除 / 重新导入）。

为什么能纯离线跑：这一层的外部依赖被整体替换成临时实现——
向量库用内存库（hash embedding，不联网）、元数据用临时 SQLite、上传目录用 tmp_path。
只有换成真实组件时它才需要 Milvus / PostgreSQL，因此不属于 integration 标记。

重点守护两件最容易静默出错的事：
1. **删除要真的删干净**（向量 + 文件 + 元数据），只删元数据会留下"界面没了但还能被检索到"的幽灵语料；
2. **重复入库不能翻倍**（doc_id 由文件名决定，更新语料必然落到同一个 doc_id）。
"""
import types
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.vectorstore as vs
from app.database import Base
from app.services import corpus as svc
from app.services.vectorstore import MemoryVectorStore


def _long_text(paragraphs: int = 12) -> str:
    """够长的正文：保证能被切成多个片段（测试里 CHUNK_SIZE 已调到 120）。"""
    return "\n".join(
        f"第{i}条 申请人应当携带身份证明材料到政务服务窗口办理社会保障卡申领业务，"
        f"受理通过后按通知领取。"
        for i in range(paragraphs)
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    """把语料管理这一层的外部依赖换成临时实现。"""
    from app.config import settings

    monkeypatch.setattr(settings, "VECTOR_STORE", "memory")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "hash")
    monkeypatch.setattr(settings, "PIPELINE", "native")
    monkeypatch.setattr(settings, "CHUNK_SIZE", 120)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP", 20)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "DOCS_DIR", str(tmp_path / "corpus"))
    (tmp_path / "corpus").mkdir(exist_ok=True)

    store = MemoryVectorStore(persist_path=tmp_path / "vec.json")
    monkeypatch.setattr(vs, "_store", store)
    monkeypatch.setattr(vs, "_embedding", None)

    # 元数据换库：必须在两个 service 模块里替换 SessionLocal 引用，
    # 它们都是 `from ..database import SessionLocal` 绑定到模块级的名字，
    # 只改 app.database 不会影响已导入的引用。
    engine = create_engine(f"sqlite:///{tmp_path / 'corpus_meta.db'}", future=True)
    Base.metadata.create_all(bind=engine)
    SM = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
    monkeypatch.setattr("app.services.corpus.SessionLocal", SM)
    monkeypatch.setattr("app.services.ingest.SessionLocal", SM)

    return types.SimpleNamespace(
        store=store,
        uploads=settings.upload_dir,
        builtin=settings.docs_dir,
        settings=settings,
    )


class TestExtractTitle:
    """PDF 页眉里的 URL 不能当文档名——实测上传 qz.pdf 就拿到过
    "指南地址:https://www.gdzwfw.gov.cn/..."，列表里完全没法认。"""

    def test_url_header_line_skipped(self):
        from app.services.ingest import extract_title

        text = "指南地址:https://www.gdzwfw.gov.cn/portal/v2/guide/123\n办理残疾人证\n受理范围：…"
        assert extract_title(text, Path("qz.pdf")) == "办理残疾人证"

    def test_meaningful_filename_wins(self):
        from app.services.ingest import extract_title

        assert extract_title("正文", Path("GD01_个体工商户设立登记_广东政务网.txt")) == "个体工商户设立登记"

    def test_override_wins_over_filename(self):
        from app.services.ingest import extract_title

        assert extract_title("正文", Path("GD01_个体工商户设立登记_广东政务网.txt"), "我的名字") == "我的名字"


class TestSafeFilename:
    def test_strips_directory_prefix(self):
        """路径穿越：../../etc/passwd 必须只剩 passwd。"""
        assert svc.safe_filename("../../etc/passwd") == "passwd"

    def test_keeps_chinese_and_suffix(self):
        assert svc.safe_filename("居住证办理指南 v2.txt") == "居住证办理指南_v2.txt"

    def test_empty_name_falls_back(self):
        assert svc.safe_filename("").endswith("upload")


class TestAddText:
    def test_ingest_and_list(self, env):
        r = svc.add_text("测试语料", _long_text())
        assert r["chunks"] > 0
        assert (env.uploads / f"{r['source']}").exists()

        listing = svc.list_documents()
        assert listing["total"] == 1
        doc = listing["docs"][0]
        assert doc["doc_name"] == "测试语料"
        assert doc["chunks"] == r["chunks"]
        assert doc["origin"] == svc.ORIGIN_UPLOADED
        assert listing["total_chunks"] == r["chunks"]

    def test_reimport_does_not_duplicate_chunks(self, env):
        """同一标题入库两次：片段数不能翻倍（先清旧片段再写入）。"""
        first = svc.add_text("测试语料", _long_text())
        second = svc.add_text("测试语料", _long_text())
        assert second["doc_id"] == first["doc_id"]
        assert second["chunks"] == first["chunks"]
        assert env.store.count() == first["chunks"]

    def test_rejects_too_short_content(self, env):
        with pytest.raises(ValueError):
            svc.add_text("测试语料", "太短了")

    def test_failed_ingest_leaves_no_file(self, env):
        """入库失败要连文件一起清掉，否则界面上看不到、下次还会被静默覆盖。"""
        with pytest.raises(ValueError):
            svc.add_text("空语料", "  \n  \t ")
        assert not any(env.uploads.iterdir())


class TestAddDocument:
    def test_rejects_unsupported_type(self, env):
        with pytest.raises(ValueError, match="不支持的文件类型"):
            svc.add_document("virus.exe", b"MZ" * 100)

    def test_rejects_oversize(self, env, monkeypatch):
        monkeypatch.setattr(env.settings, "MAX_UPLOAD_MB", 1)
        with pytest.raises(ValueError, match="超过"):
            svc.add_document("大文件.txt", b"a" * (2 * 1024 * 1024))

    def test_rejects_empty_file(self, env):
        with pytest.raises(ValueError):
            svc.add_document("空.txt", b"")

    def test_custom_title_overrides_filename(self, env):
        """文件名无语义（qz.pdf / 文档1.docx）时，用户填的标题必须生效。"""
        r = svc.add_document("qz.txt", _long_text().encode("utf-8"), title="残疾人证办理指南")
        assert r["doc_name"] == "残疾人证办理指南"
        assert r["source"] == "qz.txt"

    def test_accepts_txt(self, env):
        r = svc.add_document("窗口办事须知.txt", _long_text().encode("utf-8"))
        assert r["chunks"] > 0
        assert r["source"] == "窗口办事须知.txt"


class TestWriteSerialization:
    """"更新语料"是先清旧片段再写入，中间有几十秒的 Embedding 窗口。
    两个写操作一旦交错，就会留下半新半旧的片段 —— 必须串行。"""

    def test_concurrent_ingest_is_serialized(self, env, monkeypatch):
        import threading as th
        import time

        def slow(*_a, **_kw):
            time.sleep(0.4)
            return {"doc_id": "x", "doc_name": "x", "source": "x.txt", "chunks": 1, "status": "ok"}

        monkeypatch.setattr("app.services.corpus._ingest", slow)

        errors = []

        def run(i):
            try:
                svc.add_text(f"并发语料{i}", _long_text())
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        t0 = time.time()
        threads = [th.Thread(target=run, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        cost = time.time() - t0

        assert not errors, errors
        assert cost >= 0.75, f"两次入库没有串行（{cost:.2f}s），写操作必须互斥"


class TestBuiltinClash:
    """上传文件绝不能顶掉内置基准语料。"""

    def test_same_name_as_builtin_is_renamed(self, env):
        """doc_id 由文件名哈希而来，同名 = 直接覆盖内置语料的片段。"""
        from app.services.ingest import ingest_file

        builtin = env.builtin / "GD01_个体工商户设立登记_广东政务网.txt"
        builtin.write_text(_long_text(), encoding="utf-8")
        r0 = ingest_file(builtin)
        before = env.store.count()

        r = svc.add_document(builtin.name, _long_text().encode("utf-8"), title="我上传的同名语料")
        assert r["source"] != builtin.name, "落盘名必须改开，否则会顶掉内置语料"
        assert r["doc_id"] != r0["doc_id"]

        # 内置语料的片段没被动过
        stats = env.store.doc_stats()
        assert stats.get(r0["doc_id"], 0) == r0["chunks"]
        assert env.store.count() == before + r["chunks"]
        assert builtin.exists()

    def test_failed_update_tells_user_old_chunks_are_gone(self, env, monkeypatch):
        """覆盖入库失败时，旧片段已经被清掉了 —— 必须说清楚，不能只报"入库失败"。"""
        svc.add_text("待覆盖语料", _long_text())

        def boom(*a, **kw):
            raise RuntimeError("Embedding 挂了")

        monkeypatch.setattr("app.services.corpus._ingest", boom)
        with pytest.raises(ValueError, match="旧片段已被移除"):
            svc.add_text("待覆盖语料", _long_text())


class TestDelete:
    def test_removes_vectors_file_and_meta(self, env):
        r = svc.add_text("待删除语料", _long_text())
        out = svc.delete_document(r["doc_id"])

        assert out["removed_chunks"] == r["chunks"]
        assert out["file_removed"] is True
        assert out["recoverable"] is False
        assert env.store.count() == 0
        assert not any(env.uploads.iterdir())
        assert svc.list_documents()["total"] == 0

    def test_builtin_keeps_source_file_and_can_reingest(self, env):
        """内置语料只清向量、不动源文件，且必须能重新导入回来。"""
        from app.services.ingest import ingest_file

        src = env.builtin / "GD99_测试内置语料.txt"
        src.write_text(_long_text(), encoding="utf-8")
        doc_id = ingest_file(src)["doc_id"]
        assert env.store.count() > 0

        out = svc.delete_document(doc_id)
        assert out["file_removed"] is False
        assert out["meta_removed"] is False, "删掉元数据就无法再重新导入了"
        assert out["recoverable"] is True
        assert src.exists(), "内置语料源文件不能被删"
        assert env.store.count() == 0

        # 列表里仍要看得见它，且标记为"已移出检索库"
        doc = svc.list_documents()["docs"][0]
        assert doc["chunks"] == 0 and doc["in_index"] is False
        assert doc["origin"] == svc.ORIGIN_BUILTIN
        assert doc["can_reingest"] is True

        back = svc.reingest_document(doc_id)
        assert back["chunks"] > 0
        assert env.store.count() == back["chunks"]
        assert svc.list_documents()["docs"][0]["in_index"] is True

    def test_unknown_doc_raises_keyerror(self, env):
        with pytest.raises(KeyError):
            svc.delete_document("not-exist")


class TestWorkbenchToken:
    """凭证校验必须是"可开关"的：不配置时老部署行为完全不变。"""

    def test_disabled_by_default(self, env):
        from app.routers.corpus import verify_token

        assert not (env.settings.CORPUS_WRITE_TOKEN or "").strip()
        verify_token(None)          # 不配置 -> 放行，不抛异常

    def test_wrong_token_rejected(self, env, monkeypatch):
        from app.routers.corpus import verify_token

        monkeypatch.setattr(env.settings, "CORPUS_WRITE_TOKEN", "secret-abc")
        with pytest.raises(HTTPException) as ei:
            verify_token("wrong")
        assert ei.value.status_code == 403
        with pytest.raises(HTTPException):
            verify_token(None)

    def test_right_token_passes(self, env, monkeypatch):
        from app.routers.corpus import verify_token

        monkeypatch.setattr(env.settings, "CORPUS_WRITE_TOKEN", "secret-abc")
        verify_token("secret-abc")
        verify_token("  secret-abc  ")   # 首尾空白容错：手动抄 token 常带空格


class TestListChunks:
    """切分预览：能看见每篇被切成了什么，调 CHUNK_SIZE 时不用靠猜。"""

    def test_returns_chunks_in_order(self, env):
        r = svc.add_text("预览用语料", _long_text())
        out = svc.list_chunks(r["doc_id"], limit=50)
        assert out["doc_name"] == "预览用语料"
        assert out["shown"] == r["chunks"]
        assert [c["index"] for c in out["chunks"]] == sorted(
            c["index"] for c in out["chunks"]
        ), "片段必须按 chunk_index 排序，乱序说明排序没生效"
        assert all(c["chars"] > 0 for c in out["chunks"])
        assert all(c["text"] for c in out["chunks"])

    def test_respects_limit(self, env):
        r = svc.add_text("预览用语料", _long_text(paragraphs=30))
        assert len(svc.list_chunks(r["doc_id"], limit=2)["chunks"]) == 2

    def test_unknown_doc_raises_keyerror(self, env):
        with pytest.raises(KeyError):
            svc.list_chunks("not-exist")


class TestRouterErrorMapping:
    """路由层只做错误码映射，这里用真实路由函数验证映射正确。"""

    def test_unknown_doc_maps_to_404(self, env):
        from app.routers.corpus import delete_corpus

        with pytest.raises(HTTPException) as ei:
            delete_corpus("not-exist")
        assert ei.value.status_code == 404

    def test_bad_file_type_maps_to_400(self, env):
        from io import BytesIO

        from app.routers.corpus import upload_corpus

        up = UploadFile(file=BytesIO(b"MZ" * 50), filename="virus.exe")
        with pytest.raises(HTTPException) as ei:
            upload_corpus(up)
        assert ei.value.status_code == 400

    def test_short_content_rejected_by_schema(self, env):
        """过短正文在 schema 层就被挡掉，走不到路由（FastAPI 会转成 422）。"""
        from pydantic import ValidationError

        from app.schemas import CorpusTextRequest

        with pytest.raises(ValidationError):
            CorpusTextRequest(title="标题", content="太短")
