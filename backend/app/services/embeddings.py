"""Embedding 封装：hash（离线）/ OpenAI 兼容 / 通义千问原生多模态接口。"""
from __future__ import annotations

import hashlib
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..config import settings


def _normalize(vec: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


class BaseEmbedding(ABC):
    name = "base"

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """返回 shape=(len(texts), dim) 的 L2 归一化向量矩阵。"""


class HashEmbedding(BaseEmbedding):
    """本地哈希向量：无网络依赖，按字符 n-gram 加权，适合演示与离线开发。"""

    name = "hash"
    DIM = 1024

    def __init__(self, dim: int = DIM):
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> list[str]:
        t = re.sub(r"\s+", "", text.lower())
        if not t:
            return []
        toks = [f"#{c}" for c in t]          # 单字
        toks += [t[i : i + 2] for i in range(len(t) - 1)]  # 二元组
        toks += [t[i : i + 3] for i in range(len(t) - 2)]  # 三元组
        return toks

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in self._tokens(text):
            digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=4).digest()
            idx = int.from_bytes(digest, "big") % self.dim
            # 长 token 权重更高，提升区分度
            vec[idx] += 1.0 + 0.3 * (len(tok) - 1)
        return _normalize(vec)

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.vstack([self._one(t or "") for t in texts]) if texts else np.zeros((0, self.dim))

    @property
    def dimension(self) -> int:
        return self.dim


class OpenAICompatEmbedding(BaseEmbedding):
    """OpenAI / 通义千问（兼容模式）Embedding。

    两个关键约束：
    1. **单请求条数上限**。DashScope 文本向量（text-embedding-v3/v4、
       qwen3.7-text-embedding-flash）一次最多提交 **20** 条，早期实现把整篇文档的
       上百个片段一次性丢进去，会直接被服务端拒。因此这里必须分批。
    2. **超时**。Embedding 要独立超时（EMBED_TIMEOUT），不能复用 LLM_TIMEOUT(300s)，
       否则一次挂起会阻塞整个请求线程。
    """

    name = "openai"

    # 单批条数：DashScope 硬上限 20，留一半余量避免 token 超限连带失败
    BATCH_SIZE = 10

    def __init__(self, api_key: str, base_url: str, model: str, dim: int = 1024):
        from openai import OpenAI  # 延迟导入，未安装时不影响其他模式

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=settings.EMBED_TIMEOUT)
        self.model = model
        self.dim = int(dim)

    def _call(self, batch: list[str], retries: int = 4) -> list[list[float]]:
        last = "unknown error"
        for attempt in range(retries):
            try:
                kwargs = {"model": self.model, "input": batch}
                # dimensions 只有部分模型支持（如不支持会报错，下面兜底去掉重试）
                if self.dim:
                    kwargs["dimensions"] = self.dim
                resp = self.client.embeddings.create(**kwargs)
                data = sorted(resp.data, key=lambda x: x.index)
                return [d.embedding for d in data]
            except Exception as e:  # noqa: BLE001
                last = str(e)[:200]
                if "dimensions" in last and self.dim:
                    self.dim = 0  # 该模型不支持自定义维度，改用默认维度重试
                    continue
            time.sleep(min(1.5 * (2**attempt), 8.0))
        raise RuntimeError(f"OpenAI 兼容 Embedding 调用失败：{last}")

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim or 1024), dtype=np.float32)
        batches = [texts[i : i + self.BATCH_SIZE] for i in range(0, len(texts), self.BATCH_SIZE)]
        out: list[list[float] | None] = [None] * len(batches)
        workers = min(len(batches), max(1, int(settings.EMBED_WORKERS)))
        if workers == 1:
            for i, b in enumerate(batches):
                out[i] = self._call(b)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(self._call, b): i for i, b in enumerate(batches)}
                for fut in futs:
                    out[futs[fut]] = fut.result()

        flat: list[list[float]] = []
        for v in out:
            flat.extend(v or [])
        mat = np.array(flat, dtype=np.float32)
        mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12)
        self.dim = mat.shape[1]
        return mat

    @property
    def dimension(self) -> int:
        return self.dim


class DashScopeNativeEmbedding(BaseEmbedding):
    """通义千问多模态向量原生接口（tongyi-embedding-vision-flash / qwen3-vl-embedding）。

    注意：这条线上的模型【不支持 OpenAI 兼容模式】，必须调用原生端点
    /api/v1/services/embeddings/multimodal-embedding/multimodal-embedding，
    且一次只能提交一条内容，因此这里用线程池并发。

    不同模型维度不同（vision-flash=768 / qwen3-vl-embedding=2560），
    构造时传进来的 dim 只是"建库前的预期值"，真正维度以首次调用返回为准
    （见 embed() 里的 self.dim 回写）。配置写错会在 Milvus 里触发删集合重建，
    因此 scripts/check_env.py 会做一次实测校验。
    """

    name = "dashscope_native"

    def __init__(
        self,
        api_key: str,
        model: str = "tongyi-embedding-vision-flash",
        url: str | None = None,
        dim: int = 768,
        workers: int = 6,
    ):
        import requests  # 延迟导入

        self._requests = requests
        self.api_key = api_key
        self.model = model
        self.url = url or settings.DASHSCOPE_NATIVE_EMBED_URL
        self.dim = int(dim)
        self.workers = max(1, int(workers))

    def _one(self, text: str, retries: int = 4) -> list[float]:
        payload = {"model": self.model, "input": {"contents": [{"text": text or ""}]}}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last = "unknown error"
        for attempt in range(retries):
            try:
                r = self._requests.post(
                    self.url,
                    headers=headers,
                    json=payload,
                    timeout=settings.EMBED_TIMEOUT,
                )
                if r.status_code == 200:
                    data = r.json()
                    return data["output"]["embeddings"][0]["embedding"]
                last = f"HTTP {r.status_code}: {r.text[:150]}"
            except Exception as e:  # noqa: BLE001
                last = str(e)[:150]
            # 指数退避：限流时给服务端一点恢复时间
            time.sleep(min(1.5 * (2**attempt), 8.0))
        raise RuntimeError(f"DashScope 向量化失败：{last}")

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out: list[list[float] | None] = [None] * len(texts)
        if len(texts) == 1:
            out[0] = self._one(texts[0])
        else:
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                futs = {ex.submit(self._one, t): i for i, t in enumerate(texts)}
                for fut in futs:
                    out[futs[fut]] = fut.result()
        mat = np.array([v for v in out if v is not None], dtype=np.float32)
        mat = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12)
        self.dim = mat.shape[1]
        return mat

    @property
    def dimension(self) -> int:
        return self.dim


def build_embedding() -> BaseEmbedding:
    """按配置创建 Embedding 实例，失败时自动降级为本地哈希向量。"""
    provider = (settings.EMBEDDING_PROVIDER or "hash").lower()
    try:
        if provider == "openai" and settings.OPENAI_API_KEY:
            return OpenAICompatEmbedding(
                settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL, settings.OPENAI_EMBED_MODEL
            )
        if provider == "dashscope" and settings.DASHSCOPE_API_KEY:
            return OpenAICompatEmbedding(
                settings.DASHSCOPE_API_KEY, settings.DASHSCOPE_BASE_URL, settings.DASHSCOPE_EMBED_MODEL
            )
        if provider == "dashscope_native" and settings.DASHSCOPE_API_KEY:
            return DashScopeNativeEmbedding(
                settings.DASHSCOPE_API_KEY,
                settings.DASHSCOPE_EMBED_MODEL or "tongyi-embedding-vision-flash",
                dim=settings.VECTOR_DIM,
            )
    except Exception as e:  # noqa: BLE001
        print(f"[warn] Embedding 初始化失败，降级为本地哈希向量：{e}")

    if provider != "hash":
        print(f"[warn] EMBEDDING_PROVIDER={provider} 未配置密钥，使用本地哈希向量")
    return HashEmbedding()
