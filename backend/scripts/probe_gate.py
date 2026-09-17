"""口语化泛问探测：打印每个问题的 Top-1 三通道分数与闸门判定。

用法：
    docker cp backend/scripts/probe_gate.py gov-backend:/app/scripts/
    docker exec gov-backend python scripts/probe_gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.pipeline import get_rag_service  # noqa: E402

# 口语化泛问：库里有对应事项，但说法很生活化
COLLOQUIAL: list[str] = [
    "我想开个小店，要办啥？",
    "我想办个证",
    "社保怎么办",
    "我的店不想开了，要办什么手续",
    "房子过户咋弄",
    "我要办居住证",
    "怎么办证",
    # 32 篇新语料（GD12~GD31）的口语说法
    "生完孩子能领什么钱",
    "在老家看病怎么报销",
    "公积金里的钱怎么取出来",
    "想当老师要考什么证",
    "不干了失业保险怎么领",
    "上班受伤了算工伤吗",
    "帮我看看要带啥东西",
    "医保报销能报多少",
    "孩子上学要什么手续",
    "办个营业执照要多久",
    "想把自己的店改名了，怎么办",
    "外地人在这边交社保怎么弄",
    "请问怎么办理",
    "我想申请补贴",
]

# 标准问法（应当命中，作为对照）。覆盖新旧语料，语料扩充后同步补。
STANDARD: list[str] = [
    "个体工商户设立登记需要哪些材料？",
    "居住证怎么申领？",
    "不动产转移登记需要哪些材料？",
    "生育津贴怎么申领？",
    "异地就医备案怎么办？",
    "住房公积金租房提取需要什么材料？",
    "内地居民结婚登记需要什么材料？",
    "普通护照首次申领要什么材料？",
    "食品经营许可证怎么核发？",
    "教师资格认定怎么办？",
    # GD32（2026-09-15 入库）
    "社会保障卡怎么申领？",
    "社保卡办理需要什么材料？",
]

# 域外（应当拒答）
OUT_DOMAIN: list[str] = [
    "今天天气怎么样？",
    "怎么做番茄炒蛋？",
    "推荐一部好看的电影",
    "北京有哪些景点？",
    "Python 快速排序怎么写？",
    "帮我写一首诗",
]

# 像政务但知识库没收录（最容易漏进来的一条，语料扩充后要重新挑）
NEAR_MISS: list[str] = [
    "烟草专卖零售许可证怎么办理？",
    "犬类准养证怎么办？",
    "低保怎么申请？",
    "残疾人证怎么办理？",
]


def run(rag, group: str, questions: list[str]) -> None:
    print(f"\n===== {group} =====")
    print(
        f"{'问题':<24} {'vec1':>6} {'vec2':>6} {'差':>6} {'kw1':>7} {'融合':>6} "
        f" 判定   Top1 文档 / Top2 文档"
    )
    for q in questions:
        try:
            hits = rag.retrieve(q)
        except Exception as e:  # noqa: BLE001
            print(f"{q:<24} 检索失败：{e}")
            continue
        if not hits:
            print(f"{q:<24} 无召回")
            continue
        h = hits[0]
        second = next((x for x in hits[1:] if x.doc_id != h.doc_id), None)
        v2 = second.vector_score if second else 0.0
        name2 = second.doc_name if second else "-"
        ok = rag._is_relevant(h)
        print(
            f"{q:<24} {h.vector_score:>6.3f} {v2:>6.3f} {h.vector_score - v2:>6.3f}"
            f" {h.keyword_score:>7.2f} {h.score:>6.3f}  {'放行' if ok else '拦截'}"
            f"  {h.doc_name[:16]} / {name2[:16]}"
        )


def main() -> int:
    rag = get_rag_service()
    print(f"向量库={rag.store.name} 片段={rag.store.count()}")
    print(
        f"阈值 VECTOR_MIN={settings.VECTOR_MIN_SCORE} "
        f"KEYWORD_MIN={settings.KEYWORD_MIN_SCORE} "
        f"SIMILARITY={settings.SIMILARITY_THRESHOLD}"
    )
    run(rag, "标准问法", STANDARD)
    run(rag, "口语化泛问", COLLOQUIAL)
    run(rag, "域外", OUT_DOMAIN)
    run(rag, "像政务但未收录", NEAR_MISS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
