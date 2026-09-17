"""接口冒烟测试：验证 RAG 检索质量、材料清单生成与容错。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def post(path, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # 推理模型单轮可能很久（LLM_TIMEOUT=300），这里必须留足余量
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    print("health:", get("/api/health"))
    sid = post("/api/session/create")["session_id"]
    print("session:", sid)

    questions = [
        "办理社保卡需要什么材料？",
        "租房怎么提取公积金？",
        "个体工商户营业执照怎么办？",
        "居住证怎么申领？",
        "异地就医备案怎么办理？",
        "今天天气怎么样？",
    ]
    for q in questions:
        r = post("/api/chat", {"session_id": sid, "question": q})
        m = r.get("material_list")
        print("=" * 70)
        print("Q:", q)
        print("A:", r["answer"][:100].replace("\n", " "))
        print("SRC:", [f'{s["doc_name"]}/{s["section"]}={s["score"]}' for s in r["sources"][:3]])
        if m:
            print(
                f'MAT: {m["title"]} | 部门={m["department"] or "-"} | 时限={m["legal_time"] or "-"} '
                f'| 必备={len(m["required"])} 可选={len(m["optional"])} 流程={len(m["steps"])} 提示={len(m["tips"])}'
            )
            for i in m["required"][:3]:
                print("   -", i["name"], "|", i["desc"][:30], "|", i["count"])
        else:
            print("MAT: None")

    hist = get(f"/api/chat/history?session_id={sid}")
    print("=" * 70)
    print("history records:", len(hist), "| last:", hist[-1]["question"])

    # 参数校验
    try:
        post("/api/chat", {"session_id": sid, "question": "  "})
    except Exception as e:
        print("validation ->", e)


if __name__ == "__main__":
    main()
