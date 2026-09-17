"""RAG 回归评测：域内问题必须命中正确文档，域外问题必须拒答。

五组用例：
    1. 域内基础        —— 命中正确文档 + 给出材料清单（且不得拒答）
    2. 挑战·易混淆     —— 相似事项（设立/变更/注销、申领/签注）首选文档必须对
    3. 挑战·数值精确   —— 承诺办结时限等结构化字段必须答对
    4. 挑战·领域内未收录 —— 护照/公租房等"像政务但没收录"的必须拒答
    5. 域外拒答        —— 明显无关问题必须拒答

用法：
    python scripts/eval_rag.py              # 全量（约 6 分钟）
    python scripts/eval_rag.py --quick      # 只跑第 1 组

退出码：全部通过 0，否则 1。
前提：后端已启动（默认 http://127.0.0.1:8000）。
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
REFUSAL = "暂无该业务相关政策"
GUIDE = "语义最相近的政务事项"   # 泛问引导话术特征（见 prompts.VAGUE_GUIDE_ANSWER）

# (问题, 期望命中的文档名关键字, 必备材料最少条数)
IN_DOMAIN: list[tuple[str, str, int]] = [
    ("个体工商户设立登记需要哪些材料？", "个体工商户设立登记", 1),
    ("办理个体工商户营业执照怎么办？", "个体工商户", 0),
    ("城乡居民养老保险参保登记需要什么材料？", "城乡居民养老保险参保登记", 1),
    ("居住证怎么申领？", "申领居住证", 1),
    ("居住证签注需要什么材料？", "签注居住证", 1),
    # 语料补全后才转为正例：原先 GD03/GD03b 只有《居住证暂行条例》式的依据条文，
    # 没有签注的办事指南，这题只能拒答。现从广东政务服务网补入
    # GD11_签注居住证（事项版本 4），才具备"必须答出来"的前提。
    ("居住证到期了怎么续期？", "签注居住证", 1),
    ("灵活就业社保补贴怎么申领？", "灵活就业社保补贴申领", 0),
    ("一次性创业资助需要什么材料？", "一次性创业资助申领", 1),
    ("个体工商户变更登记怎么办？", "个体工商户变更登记", 0),
    ("个体工商户注销登记需要什么材料？", "个体工商户注销登记", 1),
    # 语料从 12 篇扩到 32 篇后补入的正例（GD12~GD30）
    ("生育津贴怎么申领？", "生育津贴申领", 1),
    ("异地就医备案怎么办理？", "异地就医备案", 1),
    ("住房公积金租房提取需要什么材料？", "住房公积金租房提取", 1),
    ("内地居民结婚登记需要什么材料？", "内地居民结婚登记", 1),
    ("普通护照首次申领要什么材料？", "普通护照首次申领", 1),
    ("房屋所有权首次登记需要哪些材料？", "房屋所有权首次登记", 1),
    ("不动产转移登记需要哪些材料？", "不动产转移登记", 1),
    ("高校毕业生就业创业补贴怎么申领？", "高校毕业生", 0),
]

OUT_DOMAIN: list[str] = [
    "今天天气怎么样？",
    "帮我写一首诗",
    "北京有哪些景点？",
    "Python 快速排序怎么写？",
    "推荐一部好看的电影",
]

# ---- 挑战集：比基础用例更难，专门打检索质量的薄弱处 ----

# (问题, 首选文档必须含的关键字)。
# 这几个事项两两高度相似（设立/变更/注销、申领/签注），
# 检索一旦被"关键词磁铁"带偏，首选文档就会错。
DISAMBIGUATION: list[tuple[str, str]] = [
    ("个体工商户不想开了要办什么登记？", "注销登记"),
    ("我的店要改名字，需要办什么登记？", "变更登记"),
    ("第一次申领居住证需要什么材料？", "申领居住证"),
]

# 历史：这里曾放「居住证到期了怎么续期？」，断言它**必须拒答**。
# 因为当时语料里 GD03/GD03b 的"签注"只出现在《居住证暂行条例》式的依据段落
# （"居住证每年签注一次…到派出所办理签注手续"），没有该事项的材料/流程/时限。
# 现已从广东政务服务网补入 `GD11_签注居住证_广东政务网.txt`（20 片段），
# 该问题已能正常作答，因此移回域内正例。
# 保留这个分组名是为了说明：**"拒答"有时是正确行为，但先要确认语料真的没有**。
CITATION_ONLY: list[str] = []

# (问题, 答案里必须出现的数字)。检验结构化字段有没有被检索/生成阶段丢掉。
# 期望值取自语料原件：设立1 / 居住证申领5 / 社保补贴30 / 创业资助20（工作日）
NUMERIC: list[tuple[str, str]] = [
    ("个体工商户设立登记承诺几个工作日办结？", "1"),
    ("申领居住证承诺办结时限是多久？", "5"),
    ("灵活就业社保补贴申领承诺多少个工作日办结？", "30"),
    ("一次性创业资助申领承诺办结时限是多少个工作日？", "20"),
]

# 政务领域内、但知识库未收录的事项 —— 最容易骗过闸门去编造的一类。
# 与 OUT_DOMAIN 的区别：这些语义上离已收录事项很近，闸门更容易放行。
#
# ⚠️ 语料扩充后必须重挑：原用例（护照/公租房/外地车牌/港澳通行证）已随
# GD23/GD31/GD24 入库变成"已收录"，继续用会误判为"未拒答"。
NEAR_MISS: list[str] = [
    "烟草专卖零售许可证怎么办理？",
    "犬类准养证怎么办？",
    "低保怎么申请？",
    "残疾人证怎么办理？",
]


def post(path: str, data=None) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


RETRIEVAL_DOWN = "检索服务暂时不可用"


def ask(question: str, tries: int = 3) -> dict:
    """每个问题开一个新会话，避免多轮历史干扰评测。

    Embedding 走公网，偶发限流/连接失败，这里重试几次，
    否则一次网络抖动就会让回归评测误报。
    """
    last: Exception | None = None
    for i in range(tries):
        try:
            sid = post("/api/session/create")["session_id"]
            r = post("/api/chat", {"session_id": sid, "question": question})
            if RETRIEVAL_DOWN in (r.get("answer") or ""):
                raise RuntimeError("检索服务瞬时不可用")
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def hit(r: dict) -> bool:
    """是否命中知识库。

    注意：ChatResponse 不返回 hit 字段（接口契约里没有），
    只能用 sources 是否为空来判断 —— 未命中时后端会直接返回空 sources。
    """
    return bool(r.get("sources"))


def check_in_domain(q: str, expect: str, min_required: int) -> tuple[bool, str]:
    r = ask(q)
    if not hit(r):
        return False, "未命中（被闸门拦截）"
    # 命中不等于答得出来：检索成功但模型仍可能判定"资料里没说"，返回拒答话术。
    # 早期只查"文档对不对 + 材料条数"，于是"有溯源 + 拒答"这种自相矛盾的响应
    # 会被判成通过（实测"居住证到期了怎么续期"就是这样混过去的）。
    # 只把"整段就是拒答"判为拒答。答对了主体、末尾补一句"细节未收录"不算拒答
    # —— 那种回答是有用的，用 `in` 判断会误伤（实测把"应当办理注销登记…"
    # 这种正答也判成了拒答）。
    ans = (r.get("answer") or "").strip()
    if ans.startswith(REFUSAL):
        return False, f"检索命中却拒答（{len(r.get('sources') or [])} 条溯源）→ {ans[:50]}"
    docs = [s["doc_name"] for s in r.get("sources") or []]
    title = ((r.get("material_list") or {}).get("title")) or ""
    if expect not in " ".join(docs) and expect not in title:
        return False, f"命中文档不符：{docs[:2]} / title={title!r}"

    m = r.get("material_list") or {}
    n = len(m.get("required") or [])
    if n < min_required:
        return False, f"必备材料 {n} 条 < 期望 {min_required} 条"
    detail = f'{m.get("title") or docs[0]} | 必备={n} 流程={len(m.get("steps") or [])}'
    return True, detail


def check_out_domain(q: str) -> tuple[bool, str]:
    r = ask(q)
    if not hit(r):
        return True, "闸门拦截，未进入生成"
    ans = r.get("answer") or ""
    if REFUSAL in ans:
        return True, "大模型拒答"
    # 泛问引导也视为"未编造"：它只列出知识库里真实存在的相近事项让用户确认，
    # 不会用常识补全某个未收录事项的材料与流程（见 prompts.VAGUE_GUIDE_ANSWER）。
    if GUIDE in ans:
        return True, "泛问引导（未编造）"
    return False, "未拒答（疑似编造）→ " + ans[:60]


def check_disambiguation(q: str, must: str) -> tuple[bool, str]:
    """首选文档必须是目标事项。

    只看命中不看排序是不够的：这些事项两两相似，rerank 一旦失手，
    目标文档会掉到第 2、3 位，答案照样张冠李戴。
    """
    r = ask(q)
    if not hit(r):
        return False, "未命中（被闸门拦截）"
    ans = (r.get("answer") or "").strip()
    if ans.startswith(REFUSAL):
        return False, f"检索命中却拒答 → {ans[:50]}"
    docs = [s["doc_name"] for s in r.get("sources") or []]
    title = ((r.get("material_list") or {}).get("title")) or ""
    top = docs[0] if docs else ""
    if must not in top and must not in title:
        return False, f"首选文档不是 {must!r}：top={top!r} title={title!r}"
    return True, f"首选={top or title}"


def check_numeric(q: str, num: str) -> tuple[bool, str]:
    """答案或溯源片段里必须出现该数字。"""
    r = ask(q)
    if not hit(r):
        return False, "未命中（被闸门拦截）"
    ans = r.get("answer") or ""
    if num in ans:
        return True, f"答案含 {num}"
    snips = " ".join((s.get("snippet") or "") for s in r.get("sources") or [])
    if num in snips:
        return True, f"溯源片段含 {num}（答案未直接给出）"
    return False, f"未出现 {num}：{ans[:80]}"


def main() -> int:
    ap = argparse.ArgumentParser(description="RAG 回归评测")
    ap.add_argument("--quick", action="store_true", help="只跑域内基础用例，跳过拒答与挑战集")
    args = ap.parse_args()

    print("=" * 72)
    print(" RAG 回归评测")
    print("=" * 72)

    passed = failed = 0
    t_all = time.time()

    def run_group(title: str, cases, fn) -> tuple[int, int]:
        print(f"\n--- {title} ---")
        p = f = 0
        for case in cases:
            q = case if isinstance(case, str) else case[0]
            t0 = time.time()
            try:
                ok, detail = fn(*case) if not isinstance(case, str) else fn(case)
            except Exception as e:  # noqa: BLE001
                ok, detail = False, f"请求异常：{e}"
            cost = time.time() - t0
            print(f"  [{'PASS' if ok else 'FAIL'}] {q}  ({cost:.1f}s)")
            print(f"         {detail}")
            p += ok
            f += not ok
        return p, f

    p, f = run_group("域内：必须命中正确文档并给出材料清单", IN_DOMAIN, check_in_domain)
    passed += p
    failed += f

    if not args.quick:
        p, f = run_group("挑战·易混淆事项：首选文档必须正确", DISAMBIGUATION, check_disambiguation)
        passed += p
        failed += f

        p, f = run_group("挑战·数值精确：答案须给出正确时限", NUMERIC, check_numeric)
        passed += p
        failed += f

        if CITATION_ONLY:
            p, f = run_group("挑战·只有法规引用、没有办事指南：必须拒答", CITATION_ONLY, check_out_domain)
            passed += p
            failed += f

        p, f = run_group("挑战·领域内未收录：必须拒答（最易被编造）", NEAR_MISS, check_out_domain)
        passed += p
        failed += f

        p, f = run_group("域外：必须拒答，不得编造", OUT_DOMAIN, check_out_domain)
        passed += p
        failed += f

    print("\n" + "=" * 72)
    print(f" 通过 {passed} / {passed + failed}   总耗时 {time.time() - t_all:.1f}s")
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
