"""本地向量库的「维度漂移」防护。

换 Embedding 模型时最容易踩的坑：磁盘上还留着旧维度的向量，
而代码已经按新维度跑。Milvus 会删集合重建（看得见），
本地 JSON 库不会 —— 它会静默加载旧向量，导致：
  · 启动时 count() > 0，跳过导入，知识库「看起来是满的」
  · 检索时新查询向量与旧库做点积，分数全错且不报错
这里把该行为钉死。
"""
from __future__ import annotations

import json

import numpy as np

from app.config import settings
from app.services.vectorstore import MemoryVectorStore


def _make_store(tmp_path, dim: int, n: int = 3) -> MemoryVectorStore:
    """造一个含 n 条 dim 维向量的持久库。"""
    p = tmp_path / "vector_store.json"
    payload = {
        "ids": [f"id{i}" for i in range(n)],
        "texts": [f"材料清单 第{i}条" for i in range(n)],
        "metas": [{"doc_id": "d1", "section": "材料清单"} for _ in range(n)],
        "vectors": np.eye(n, dim, dtype=np.float32).round(6).tolist(),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return MemoryVectorStore(persist_path=p)


class TestDimGuard:
    def test_matching_dim_is_loaded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "VECTOR_DIM", 8, raising=False)
        store = _make_store(tmp_path, dim=8)
        assert store.count() == 3

    def test_mismatched_dim_is_discarded(self, tmp_path, monkeypatch):
        """旧库 4 维、配置 8 维 -> 必须丢弃重建，不能沿用。"""
        monkeypatch.setattr(settings, "VECTOR_DIM", 8, raising=False)
        store = _make_store(tmp_path, dim=4)
        assert store.count() == 0

    def test_mismatch_backs_up_old_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "VECTOR_DIM", 8, raising=False)
        p = tmp_path / "vector_store.json"
        _make_store(tmp_path, dim=4)
        assert (tmp_path / "vector_store.json.bak").exists() or not p.exists()

    def test_reverse_mismatch_also_guarded(self, tmp_path, monkeypatch):
        """降维（2560 -> 768）方向同样要拦住。"""
        monkeypatch.setattr(settings, "VECTOR_DIM", 768, raising=False)
        store = _make_store(tmp_path, dim=2560, n=2)
        assert store.count() == 0

    def test_corrupted_file_resets_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "VECTOR_DIM", 8, raising=False)
        p = tmp_path / "vector_store.json"
        p.write_text("{not json", encoding="utf-8")
        store = MemoryVectorStore(persist_path=p)
        assert store.count() == 0
