"""配置文件一致性：换 Embedding 模型时最容易漏改的地方。

背景（本项目真实踩过两次）：
1. `backend/.env` 才是应用运行时读的，根目录 `.env` 只被 docker-compose 做变量替换；
   只改其中一份，本机跑和容器跑的行为就不一样。
2. `.env.docker.example` 是给用户 `cp` 成 `.env` 的模板，它一旦停留在旧值，
   新部署会带着**旧模型的阈值**上线 —— 表现为"域外问题穿闸开始编造"，
   而且只在容器里复现，本机怎么测都测不出来。

这几个键彼此必须一致，用测试钉死，避免下次换模型再漏。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

# 换模型（Embedding 或大模型）时必须同步修改的键。
# DASHSCOPE_MODEL 原先漏在名单外：换大模型时只改 backend/.env，
# 容器里跑的仍是 compose 默认值，本机与部署行为不一致。
CRITICAL = (
    "VECTOR_DIM",
    "DASHSCOPE_EMBED_MODEL",
    "VECTOR_MIN_SCORE",
    "KEYWORD_MIN_SCORE",
    "DASHSCOPE_MODEL",
    # 2026-09-15 补：这两个原先不在名单里，结果 backend/.env 与 compose 默认值
    # 一个 0.50 一个 0.60 各跑各的都没人发现（泛问引导在容器里和本机表现不一致）。
    "FUSED_MIN_SCORE",
    "VAGUE_VECTOR_MAX",
)


def parse_env(path: Path) -> dict[str, str]:
    """解析 KEY=VALUE，忽略注释与空行；重复键取最后一个（pydantic 的行为）。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def parse_compose_defaults(path: Path) -> dict[str, str]:
    """从 `KEY: ${KEY:-default}` 里抽出默认值。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for m in re.finditer(r"^\s*([A-Z0-9_]+):\s*\$\{\1:-([^}]*)\}", path.read_text(encoding="utf-8"), re.M):
        if m.group(2):
            out[m.group(1)] = m.group(2)
    return out


@pytest.fixture(scope="module")
def files() -> dict[str, dict[str, str]]:
    # 两个 .example 也必须在列：它们是用户 cp 出来的模板，
    # 早期漏了 backend/.env.example，它一直停在 0.38/12.0 没人发现。
    return {
        "backend/.env": parse_env(BACKEND / ".env"),
        "backend/.env.example": parse_env(BACKEND / ".env.example"),
        ".env": parse_env(ROOT / ".env"),
        ".env.docker.example": parse_env(ROOT / ".env.docker.example"),
        "docker-compose.yml": parse_compose_defaults(ROOT / "docker-compose.yml"),
        "docker-compose.host.yml": parse_compose_defaults(ROOT / "docker-compose.host.yml"),
    }


@pytest.mark.parametrize("key", CRITICAL)
def test_critical_keys_present_everywhere(files, key: str):
    for name, cfg in files.items():
        assert key in cfg, f"{name} 缺少 {key}（换模型时这里必须同步改）"


@pytest.mark.parametrize("key", CRITICAL)
def test_critical_keys_agree_across_env_files(files, key: str):
    """三份 env 文件 + 两份编排的默认值必须完全相同。"""
    values = {name: cfg[key] for name, cfg in files.items() if key in cfg}
    distinct = set(values.values())
    assert len(distinct) == 1, f"{key} 在各配置文件间不一致：{values}"


def test_vector_dim_matches_embedding_model():
    """维度与模型必须配套，写反了 Milvus 会直接删集合重建。"""
    dim = int(parse_env(BACKEND / ".env").get("VECTOR_DIM", "0"))
    model = parse_env(BACKEND / ".env").get("DASHSCOPE_EMBED_MODEL", "")
    expected = {
        "tongyi-embedding-vision-flash": 768,
        "qwen3-vl-embedding": 2560,
        "text-embedding-v3": 1024,
        # 2026-09-15 起默认模型：默认 1024 维（也支持 768/512/256）
        "qwen3.7-text-embedding-flash": 1024,
    }
    if model in expected:
        assert dim == expected[model], f"{model} 应为 {expected[model]} 维，但 VECTOR_DIM={dim}"


# 真正值钱的是外部 API 凭据；POSTGRES_PASSWORD / DB_PASSWORD 这类只是
# 本地 demo 容器口令（示例文件里是弱口令 123456，仅用于一次性本地起库，
# 不视为泄露，但生产部署必须换掉）。
# \b 是必须的：LLM_MAX_TOKENS 里也含 "TOKEN"，但它显然不是凭据
_EXTERNAL_SECRET = re.compile(r"(API_KEY|ACCESS_KEY|SECRET_KEY|\bTOKEN\b)", re.I)
_PLACEHOLDER = re.compile(r"^(sk-[x*]{3,}|<.*>|\*+|your-.*)?$")


def test_no_external_secret_committed():
    """示例文件里不能带真实外部 API 凭据。"""
    for name in (".env.docker.example", "backend/.env.example"):
        p = ROOT / name
        if not p.exists():
            continue
        for k, v in parse_env(p).items():
            if not _EXTERNAL_SECRET.search(k):
                continue
            assert _PLACEHOLDER.match(v or ""), (
                f"{name} 的 {k} 不是占位符，疑似把真实密钥提交进了仓库"
            )


def test_both_compose_files_mount_corpus():
    """两份编排都必须把语料挂进容器。

    真实踩过：`docker-compose.host.yml` 少了这段挂载，容器里根本没有
    /app/data/corpus，于是文档里给的
    `exec backend python scripts/ingest.py --clear --dir /app/data/corpus`
    会导入 0 篇 —— 命令能跑通、不报错，只是知识库永远是空的。
    """
    for name in ("docker-compose.yml", "docker-compose.host.yml"):
        body = (ROOT / name).read_text(encoding="utf-8")
        assert "backend/data/corpus:/app/data/corpus" in body, f"{name} 未挂载语料目录"
        assert "DOCS_DIR" in body, f"{name} 未设置 DOCS_DIR（导入脚本会去错目录）"


def test_real_env_files_are_gitignored():
    """.gitignore 必须挡住含密钥的 .env，否则一次 add . 就泄露。"""
    gi = ROOT / ".gitignore"
    assert gi.exists(), "缺少 .gitignore"
    body = gi.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    assert ".env" in lines, ".gitignore 未忽略 .env"
