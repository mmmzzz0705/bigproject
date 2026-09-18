"""RAGService 单例的并发安全性。

要守住的性质：`__new__` 不得在 `_init()` 完成前把实例发布到 `RAGService._instance`。

`_init()` 里的 get_vector_store()/build_llm() 都是耗时操作（连 Milvus、建 LLM 客户端）。
若提前发布，并发的第二个线程会在外层 `if cls._instance is None` 处看到非 None，
直接返回一个连 `llm` 属性都还没有的半成品 —— 表现为启动后首个 /api/health 报
`AttributeError: 'RAGService' object has no attribute 'llm'`，之后自愈，极难排查。
"""
import threading
import time

import pytest

from app.services.rag import RAGService


@pytest.fixture
def _reset_singleton():
    """每个用例前后都还原单例，避免污染其它测试。"""
    saved = RAGService._instance
    RAGService._instance = None
    yield
    RAGService._instance = saved


def test_concurrent_first_call_never_yields_half_built_instance(_reset_singleton, monkeypatch):
    """并发首次调用：所有线程拿到的都必须是初始化完成的同一个实例。"""
    entered = threading.Event()

    def slow_init(self) -> None:
        self.store = object()
        self.embedding = object()
        entered.set()  # 已进 _init()，但 llm 还没挂上
        time.sleep(0.2)
        self.llm = object()

    monkeypatch.setattr(RAGService, "_init", slow_init)

    results: list[RAGService] = []
    # 必须在拿到实例的那一刻快照状态：所有线程返回的是同一个对象引用，
    # 等到 join 之后实例早被初始化线程补齐，那时再查 hasattr 永远为真。
    snapshots: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        svc = RAGService()
        with lock:
            results.append(svc)
            snapshots.append(hasattr(svc, "llm"))

    # 先只起一个线程把初始化"卡"在 _init() 里
    first = threading.Thread(target=worker)
    first.start()
    assert entered.wait(2), "初始化线程未按时启动"

    # 关键：其余线程必须在此时**之后**才调用 RAGService()，
    # 否则它们会阻塞在 _lock 上排队，等锁释放时拿到的已是完整实例 —— 那样测不出问题。
    rest = [threading.Thread(target=worker) for _ in range(4)]
    for t in rest:
        t.start()
    for t in [first, *rest]:
        t.join(5)

    assert len(results) == 5, "有线程未返回结果"
    assert all(snapshots), "有线程拿到了未初始化完的半成品实例（缺 llm 属性）"
    assert all(s is results[0] for s in results), "单例不唯一"


def test_init_failure_leaves_singleton_retryable(_reset_singleton, monkeypatch):
    """_init() 抛异常时不得把坏实例缓存下来，下次调用应可重试。"""

    def boom(self) -> None:
        raise RuntimeError("Milvus 连不上")

    monkeypatch.setattr(RAGService, "_init", boom)

    with pytest.raises(RuntimeError):
        RAGService()
    assert RAGService._instance is None, "初始化失败后不应缓存半成品实例"

    monkeypatch.setattr(RAGService, "_init", lambda self: setattr(self, "llm", object()))
    assert hasattr(RAGService(), "llm"), "初始化失败后应能重试成功"
