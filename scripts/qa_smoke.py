"""端到端冒烟：对一组口语化泛问 / 标准问法 / 域外问题调用 /api/chat，打印首段回答。

用法：
    python scripts/qa_smoke.py                # 走 http://127.0.0.1:8080
    python scripts/qa_smoke.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import json
import urllib.request
import uuid

COLLOQUIAL = [
    "我想开个小店，要办啥？",
    "我的店不想开了，要办什么手续",
    "我要办居住证",
    "房子过户咋弄",
    "办个营业执照要多久",
    "想把自己的店改名了，怎么办",
    "社保怎么办",
    "我想申请补贴",
    "怎么办证",
    "请问怎么办理",
    # 32 篇新语料（GD12~GD31）的口语说法
    "生完孩子能领什么钱",
    "在老家看病怎么报销",
    "公积金里的钱怎么取出来",
    "想当老师要考什么证",
    "不干了失业保险怎么领",
    "上班受伤了算工伤吗",
]

STANDARD = [
    "个体工商户设立登记需要哪些材料？",
    "居住证怎么申领？",
]

OUT_DOMAIN = [
    "今天天气怎么样？",
    "帮我写一首诗",
]

# 像政务但知识库未收录：应拒答（由大模型兜底，闸门可能放行）
NEAR_MISS = [
    "烟草专卖零售许可证怎么办理？",
    "犬类准养证怎么办？",
    "低保怎么申请？",
    "残疾人证怎么办理？",
]

CHARS = 160


def ask(base: str, q: str) -> dict:
    payload = json.dumps({"question": q, "session_id": uuid.uuid4().hex}).encode()
    req = urllib.request.Request(
        f"{base}/api/chat", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run(base: str, group: str, questions: list[str]) -> None:
    print(f"\n===== {group} =====")
    for q in questions:
        try:
            r = ask(base, q)
        except Exception as e:  # noqa: BLE001
            print(f"\nQ: {q}\n  [请求失败] {e}")
            continue
        ans = (r.get("answer") or "").replace("\n", " ")
        src = r.get("sources") or []
        src_txt = "、".join(s.get("doc_name", "") for s in src[:3])
        mat = r.get("material_list")
        mat_txt = f"材料{len(mat.get('required') or [])}条" if mat else "无材料卡"
        print(f"\nQ: {q}\n  溯源：{src_txt or '无'}（{mat_txt}）\n  A: {ans[:CHARS]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    args = ap.parse_args()
    run(args.base, "标准问法", STANDARD)
    run(args.base, "口语化泛问", COLLOQUIAL)
    run(args.base, "域外", OUT_DOMAIN)
    run(args.base, "像政务但未收录", NEAR_MISS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
