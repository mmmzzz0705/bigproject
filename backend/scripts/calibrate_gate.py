"""相关性闸门阈值标定。

为什么需要它
------------
`_is_relevant` 用的是**绝对分**阈值（VECTOR_MIN_SCORE / KEYWORD_MIN_SCORE），
不是融合分排序。绝对分的量纲完全由 Embedding 模型决定：

    2560 维 qwen3-vl-embedding   -> 域内 0.78~0.89、域外 0.33~0.41  -> 0.55 / 25.0
    768 维  vision-flash         -> 需要实测

所以**换模型必须重新标定**，沿用旧阈值只有两种结果：
阈值偏高 -> 域内问题被误杀成"暂无该业务相关政策"；
阈值偏低 -> 域外问题穿过闸门，大模型开始编造。

本脚本对"域内 / 域外"两组问题各跑一次检索，打印分数分布，
并给出一个能把两组分开的推荐阈值（最小化错分数）。

补充：闸门现以**向量为主判据**（见 `rag._is_relevant`）：
    vec >= VECTOR_MIN_SCORE  或  (kw >= KEYWORD_MIN_SCORE 且 融合分 >= FUSED_MIN_SCORE)
标定用的是"标准问法"，**覆盖不到口语化泛问**（"我想开个小店，要办啥"），
而后者恰恰是向量分最低的一档。标定完务必再跑
    python scripts/probe_gate.py
看口语化样本是否整体高于 VECTOR_MIN_SCORE，必要时下调 0.01~0.03。

用法：
    python scripts/calibrate_gate.py            # 打印分布 + 推荐值
    python scripts/calibrate_gate.py --write    # 直接写回 .env

前提：后端依赖已装好，且向量库已完成导入（否则域内分数全部失真）。
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.services.pipeline import get_rag_service  # noqa: E402

# 域内：知识库确实收录了的事项
IN_DOMAIN: list[str] = [
    "个体工商户设立登记需要哪些材料？",
    "城乡居民养老保险参保登记需要什么材料？",
    "居住证怎么申领？",
    "居住证签注需要什么材料？",
    "灵活就业社保补贴怎么申领？",
    "一次性创业资助需要什么材料？",
    "个体工商户变更登记怎么办？",
    "个体工商户注销登记需要什么材料？",
    "房屋所有权首次登记需要哪些材料？",
    "不动产转移登记需要哪些材料？",
    "高校毕业生就业创业补贴怎么申领？",
    "生育津贴怎么申领？",
    "异地就医备案怎么办？",
    "失业保险金怎么申领？",
    "养老保险关系怎么跨省转移？",
    "工伤认定需要什么材料？",
    "租房怎么提取住房公积金？",
    "个人住房公积金贷款怎么申请？",
    "结婚登记需要什么材料？",
    "新生儿入户需要什么材料？",
    "人才引进入户怎么办？",
    "身份证到期了怎么换领？",
    "首次申领普通护照需要什么材料？",
    "港澳通行证及签注怎么办理？",
    "驾驶证期满换证怎么办？",
    "新车上牌需要什么材料？",
    "食品经营许可证怎么办理？",
    "有限责任公司设立登记需要哪些材料？",
    "公共场所卫生许可怎么办？",
    "教师资格认定需要什么材料？",
    "公共租赁住房怎么申请？",
]

# 域外：与政务完全无关；再加一组"像政务但没收录"，后者更难拦
OUT_DOMAIN: list[str] = [
    "今天天气怎么样？",
    "帮我写一首诗",
    "北京有哪些景点？",
    "Python 快速排序怎么写？",
    "推荐一部好看的电影",
    "怎么做番茄炒蛋？",
]
# 「像政务但知识库没收录」——这是最难拦的一档，必须随语料同步维护。
# 注意：护照 / 公租房 / 港澳通行证 / 教师资格 / 公积金等事项已在 2026-09 扩语料后
# 被收录，已从本表移到 IN_DOMAIN。改动语料后务必回来核一遍。
NEAR_MISS: list[str] = [
    "外地车牌转入广州怎么办？",
    "办理离婚登记需要什么材料？",
    "烟草专卖零售许可证怎么办理？",
    "建筑工程施工许可证怎么核发？",
    "医师执业注册需要什么材料？",
    "企业年金方案备案怎么办？",
]


def probe(rag, questions: list[str]) -> list[tuple[float, float]]:
    """返回每条问题的 (最高向量分, 最高关键词分)。"""
    out: list[tuple[float, float]] = []
    for q in questions:
        try:
            hits = rag.retrieve(q)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 检索失败，跳过 {q!r}：{e}")
            continue
        if not hits:
            out.append((0.0, 0.0))
            continue
        out.append((max(h.vector_score for h in hits), max(h.keyword_score for h in hits)))
    return out


def recommend(pos: list[float], neg: list[float]) -> tuple[float, int]:
    """单通道切点：pos 应全部 >= 阈值，neg 应全部 < 阈值。

    仅供对照参考——真实闸门是「或」关系，必须用 recommend_pair。
    """
    if not pos or not neg:
        return 0.0, -1
    lo, hi = min(min(pos), min(neg)), max(max(pos), max(neg))
    best_t, best_err = lo, len(pos) + len(neg)
    steps = max(2, int((hi - lo) / 0.01) + 1)
    for i in range(steps + 1):
        t = lo + (hi - lo) * i / steps
        err = sum(1 for v in pos if v < t) + sum(1 for v in neg if v >= t)
        if err < best_err:
            best_err, best_t = err, t
    return round(best_t, 3), best_err


def _candidates(values: list[float], pad: float = 0.05, n: int = 60) -> list[float]:
    """候选切点：覆盖样本范围并向外留一点余量。"""
    if not values:
        return [0.0]
    lo, hi = min(values) - pad, max(values) + pad
    return [round(lo + (hi - lo) * i / n, 4) for i in range(n + 1)]


def recommend_pair(
    pos: list[tuple[float, float]], neg: list[tuple[float, float]]
) -> tuple[float, float, int]:
    """联合标定 (向量阈值, 关键词阈值)。

    闸门是 **或** 关系：`kw >= tk or vec >= tv` 即放行。
    因此两个阈值**不能各自独立标**——只看向量会漏掉
    「关键词分很高但语义无关」的样本，它照样能穿过闸门。
    这里做二维网格搜索，直接最小化「或」语义下的错分数：
        域内判负 = vec < tv 且 kw < tk      （被误杀）
        域外判正 = vec >= tv 或 kw >= tk    （漏进来）
    错分相同时，取离两侧样本最远的切点，把安全余量留足。
    """
    if not pos or not neg:
        return 0.0, 0.0, -1
    all_v = [p[0] for p in pos + neg]
    all_k = [p[1] for p in pos + neg]
    best = (0.0, 0.0, len(pos) + len(neg), -1.0)
    for tv in _candidates(all_v):
        for tk in _candidates(all_k):
            err = sum(1 for v, k in pos if v < tv and k < tk)
            err += sum(1 for v, k in neg if v >= tv or k >= tk)
            if err > best[2]:
                continue
            # 余量：切点到最近样本点的距离（两个通道取较小者）
            margin = min(
                min(abs(v - tv) for v in all_v) if all_v else 0.0,
                min(abs(k - tk) for k in all_k) if all_k else 0.0,
            )
            if err < best[2] or (err == best[2] and margin > best[3]):
                best = (tv, tk, err, margin)
    return round(best[0], 3), round(best[1], 3), best[2]


def fmt(xs: list[float]) -> str:
    if not xs:
        return "-"
    return (
        f"min={min(xs):.3f} p25={statistics.quantiles(xs, n=4)[0]:.3f} "
        f"median={statistics.median(xs):.3f} max={max(xs):.3f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="标定相关性闸门阈值")
    ap.add_argument("--write", action="store_true", help="把推荐值写回 .env")
    args = ap.parse_args()

    print("=" * 72)
    print(f" 相关性闸门标定   模型={settings.DASHSCOPE_EMBED_MODEL}  维度={settings.VECTOR_DIM}")
    print("=" * 72)

    rag = get_rag_service()
    n = rag.store.count()
    print(f"\n向量库：{rag.store.name}   片段数：{n}")
    if n == 0:
        print("向量库是空的 —— 先跑 scripts/ingest.py，否则标定结果没有意义。")
        return 1
    # 标定结果与向量库实现有关：Milvus 走 ANN 近似检索，top-K 与暴力检索
    # 可能差一两条，导致"域外最高关键词分"这类边界值漂移。
    # 生产用的是哪个库，就应该在哪个库上标定（本机内存库标完再上 Milvus 会偏松）。
    print(f"注意：本次标定针对 {rag.store.name}，生产用别的向量库需重新标定。")

    print("\n检索中...")
    pos = probe(rag, IN_DOMAIN)
    neg = probe(rag, OUT_DOMAIN + NEAR_MISS)

    pv = [p[0] for p in pos]
    nv = [p[0] for p in neg]
    pk = [p[1] for p in pos]
    nk = [p[1] for p in neg]

    print(f"\n向量分  域内(n={len(pv)}): {fmt(pv)}")
    print(f"向量分  域外(n={len(nv)}): {fmt(nv)}")
    print(f"关键词  域内(n={len(pk)}): {fmt(pk)}")
    print(f"关键词  域外(n={len(nk)}): {fmt(nk)}")

    tv, tk, err = recommend_pair(pos, neg)
    # 单通道切点只作对照：说明「独立标定」会漏掉什么
    _, ev = recommend(pv, nv)
    _, ek = recommend(pk, nk)

    print("\n" + "-" * 72)
    print(f" 推荐 VECTOR_MIN_SCORE  = {tv}")
    print(f" 推荐 KEYWORD_MIN_SCORE = {tk}")
    print(f" 联合错分 {err} 条（域内被误杀 + 域外漏进）")
    print(f" 当前 VECTOR_MIN_SCORE  = {settings.VECTOR_MIN_SCORE}")
    print(f" 当前 KEYWORD_MIN_SCORE = {settings.KEYWORD_MIN_SCORE}")
    print("-" * 72)
    print(f" 对照：若两个通道各自独立标定 -> 向量 {ev} 条错分 / 关键词 {ek} 条错分。")
    print("       闸门是「或」关系，独立标定会低估放行率，必须联合标定。")

    if not args.write:
        print("\n加 --write 可写回 .env")
        return 0

    # 两个都要写，原因见 README「两份 .env 的分工」：
    #   backend/.env -> 应用运行时真正读取的配置
    #   根目录 .env  -> docker-compose 变量替换（只影响容器化部署）
    backend_dir = Path(__file__).resolve().parents[1]
    targets = [backend_dir / ".env", backend_dir.parent / ".env"]

    for env in targets:
        if not env.exists():
            print(f"\n[warn] 找不到 {env}，跳过")
            continue
        s = env.read_text(encoding="utf-8")
        s, n1 = re.subn(r"^VECTOR_MIN_SCORE=.*$", f"VECTOR_MIN_SCORE={tv}", s, flags=re.M)
        s, n2 = re.subn(r"^KEYWORD_MIN_SCORE=.*$", f"KEYWORD_MIN_SCORE={tk}", s, flags=re.M)
        if not n1:
            s += f"\nVECTOR_MIN_SCORE={tv}\n"
        if not n2:
            s += f"KEYWORD_MIN_SCORE={tk}\n"
        env.write_text(s, encoding="utf-8")
        print(f"\n已写入 {env}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
