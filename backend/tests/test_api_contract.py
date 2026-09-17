"""接口契约测试。

说明：
- 用 TestClient 跑真实的 FastAPI 应用，但把 RAG 服务换成桩，
  因此**不会**调用大模型 / Embedding，只验证接口行为与持久化。
- 需要 PostgreSQL 与 Milvus 可用（应用启动会建表并探向量库）；
  不可用时整体跳过，不污染"纯离线"的单元测试。
- 会真实写入 session / chat_history，测试结束自行清理。
"""
import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402


class StubRAG:
    """只返回固定结果，避免联网调用。"""

    name = "stub"
    calls: list = []

    def answer(self, question, history=None):
        StubRAG.calls.append(question)
        return {
            "answer": "（桩回答）",
            "material_list": None,
            "sources": [],
            "mode": "stub",
            "hit": True,
        }


@pytest.fixture(scope="module")
def client():
    from app.main import app
    from app.routers import chat as chat_router

    chat_router.get_rag_service = lambda: StubRAG()

    try:
        with TestClient(app) as c:
            yield c
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"外部服务（PostgreSQL / Milvus）不可用：{e}")


@pytest.fixture
def cleanup_sessions():
    """收集测试期间创建的 session，结束后连同历史一起删除。"""
    ids: list[str] = []
    yield ids
    try:
        from app.database import SessionLocal
        from app.models import ChatHistory
        from app.models import Session as SessionModel

        with SessionLocal() as db:
            db.query(ChatHistory).filter(ChatHistory.session_id.in_(ids)).delete(
                synchronize_session=False
            )
            db.query(SessionModel).filter(SessionModel.session_id.in_(ids)).delete(
                synchronize_session=False
            )
            db.commit()
    except Exception:  # noqa: BLE001
        pass


@pytest.mark.integration
class TestHealth:
    def test_health_reports_components(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        for key in ("database", "vector_store", "doc_count", "llm_provider", "embedding_provider"):
            assert key in data, key


@pytest.mark.integration
class TestSession:
    def test_create_returns_id(self, client, cleanup_sessions):
        r = client.post("/api/session/create", json={})
        assert r.status_code == 200
        sid = r.json()["session_id"]
        assert sid
        cleanup_sessions.append(sid)


@pytest.mark.integration
class TestChat:
    def test_empty_question_rejected(self, client):
        r = client.post("/api/chat", json={"session_id": "s1", "question": "   "})
        assert r.status_code == 400

    def test_question_over_limit_rejected(self, client):
        """schema 层输入过滤：超过 1000 字直接 400，不进路由。"""
        r = client.post("/api/chat", json={"session_id": "s1", "question": "办" * 1001})
        assert r.status_code == 400

    def test_question_at_limit_accepted(self, client, cleanup_sessions):
        sid = client.post("/api/session/create", json={}).json()["session_id"]
        cleanup_sessions.append(sid)
        r = client.post("/api/chat", json={"session_id": sid, "question": "办" * 1000})
        assert r.status_code == 200

    def test_roundtrip_persists_history(self, client, cleanup_sessions):
        sid = client.post("/api/session/create", json={}).json()["session_id"]
        cleanup_sessions.append(sid)

        r = client.post("/api/chat", json={"session_id": sid, "question": "测试问题"})
        assert r.status_code == 200
        assert r.json()["answer"] == "（桩回答）"

        h = client.get(f"/api/chat/history?session_id={sid}")
        assert h.status_code == 200
        records = h.json()
        assert any(x["question"] == "测试问题" for x in records)
        assert any(x["answer"] == "（桩回答）" for x in records)

    def test_unknown_session_auto_created(self, client, cleanup_sessions):
        """前端历史会话失效时不应 500，后端会补建会话。"""
        sid = "not-exist-session-0001"
        cleanup_sessions.append(sid)
        r = client.post("/api/chat", json={"session_id": sid, "question": "测试"})
        assert r.status_code == 200

    def test_history_of_unknown_session_empty(self, client):
        r = client.get("/api/chat/history?session_id=definitely-not-exist")
        assert r.status_code == 200
        assert r.json() == []
