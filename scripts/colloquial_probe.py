"""口语化泛问效果统计：对一组口语提问判定「直接作答 / 候选引导 / 拒答」。

输出 UTF-8 文本，供论文实验章节引用。

用法：
    python scripts/colloquial_probe.py > out.txt
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"   # 直连后端：经 8080 的 Nginx 代理会在生成超过 60s 时返回 502
GUIDE = "语义最相近"
REFUSAL = "暂无该业务相关政策"

QUESTIONS: list[str] = [
    "我想开个小店，要办啥？",
    "我想办个证",
    "社保怎么办",
    "我的店不想开了，要办什么手续",
    "房子过户咋弄",
    "我要办居住证",
    "怎么办证",
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


def ask(q: str) -> dict:
    sid = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                BASE + "/api/session/create",
                data=b"{}",
                headers={"Content-Type": "application/json"},
            )
        ).read()
    )["session_id"]
    return json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                BASE + "/api/chat",
                data=json.dumps({"session_id": sid, "question": q}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ),
            timeout=300,
        ).read()
    )


def main() -> int:
    cnt = {"直接作答": 0, "候选引导": 0, "拒答": 0}
    rows: list[tuple[str, str, str]] = []
    for q in QUESTIONS:
        for _ in range(3):      # 公网 Embedding / 大模型偶发失败，重试后再判定
            try:
                r = ask(q)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[retry] {q}: {e}", flush=True)
                r = {}
        a = r.get("answer") or ""
        docs = [s.get("doc_name", "") for s in r.get("sources") or []]
        if GUIDE in a:
            kind = "候选引导"
        elif REFUSAL in a:
            kind = "拒答"
        else:
            kind = "直接作答"
        cnt[kind] += 1
        rows.append((q, kind, docs[0] if docs else "-"))
        print(f"{q}\t{kind}\t{docs[0] if docs else '-'}", flush=True)
    print("\n---- 汇总 ----")
    for k, v in cnt.items():
        print(f"{k}\t{v}\t{v / len(QUESTIONS) * 100:.1f}%")
    print(f"合计\t{len(QUESTIONS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
