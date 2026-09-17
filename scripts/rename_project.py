# -*- coding: utf-8 -*-
"""一次性脚本：把项目更名为「政明白（GovRAG）」。"""
from pathlib import Path

ROOT = Path(r"D:\group6")

SLOGAN = (
    "> **政明白** —— 让群众把办事流程「整明白」：有据可答、无据拒答、全程可溯源。\n"
    "> 英文代号 **GovRAG**（Government Retrieval-Augmented Generation），容器沿用 `gov-` 前缀。\n"
)

edits = {
    "README.md": [
        ("# 基于大语言模型的政务智能问答与办事引导系统\n",
         "# 政明白（GovRAG）· 政务智能问答与办事引导系统\n\n" + SLOGAN),
    ],
    "backend/README.md": [
        ("# 政务智能问答与办事引导系统 —— 后端服务层",
         "# 政明白（GovRAG）—— 后端服务层（FastAPI + AI 应用层）"),
    ],
    "frontend/README.md": [
        ("# 政务智能问答与办事引导系统 —— 前端展示层",
         "# 政明白（GovRAG）—— 前端展示层（Vue 3 + Vite + Nginx）"),
    ],
    "frontend/index.html": [
        ("<title>政务智能问答与办事引导系统</title>",
         "<title>政明白 · 政务智能问答与办事引导系统</title>"),
    ],
    "frontend/package.json": [
        ('"name": "gov-qa-frontend"', '"name": "govrag-frontend"'),
        ('"基于大语言模型的政务智能问答与办事引导系统 - 前端展示层"',
         '"政明白（GovRAG）政务智能问答与办事引导系统 - 前端展示层"'),
    ],
    "frontend/src/components/SideBar.vue": [
        ('<div class="t1">政务智能问答</div>', '<div class="t1">政明白</div>'),
    ],
    "docker-compose.yml": [
        ("#", "# 项目：政明白（GovRAG）—— 政务智能问答与办事引导系统\n#", 1),
    ],
    "docker-compose.host.yml": [
        ("#", "# 项目：政明白（GovRAG）—— 政务智能问答与办事引导系统\n#", 1),
    ],
    "可行性报告.md": [
        ("# 政务智能问答与办事引导系统 · 可行性报告",
         "# 政明白（GovRAG）· 可行性报告\n\n"
         "> 系统全称：政务智能问答与办事引导系统"),
    ],
}

for rel, pairs in edits.items():
    p = ROOT / rel
    t = p.read_text(encoding="utf-8")
    for item in pairs:
        old, new = item[0], item[1]
        cnt = item[2] if len(item) > 2 else None
        assert old in t, f"{rel}: 未找到 -> {old[:40]}"
        t = t.replace(old, new, cnt) if cnt else t.replace(old, new)
    p.write_text(t, encoding="utf-8")
    print("OK", rel)
