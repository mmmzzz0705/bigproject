# -*- coding: utf-8 -*-
"""一次性脚本：论文内系统称谓统一为「政明白（GovRAG）」并重命名文件。"""
from pathlib import Path

ROOT = Path(r"D:\group6")
OLD = ROOT / "学术论文_政务智能问答与办事引导系统.md"
NEW = ROOT / "学术论文_政明白GovRAG.md"

t = OLD.read_text(encoding="utf-8")

pairs = [
    # 副标题
    ('## ——以"政务智能问答与办事引导系统"为例',
     '## ——以「政明白（GovRAG）」政务问答系统为例'),
    # 中文摘要
    ('技术的政务智能问答与办事引导系统。系统采用',
     '技术的政务问答系统「政明白（GovRAG）」。该系统采用'),
    # 英文摘要
    ('this paper designs and implements an intelligent question-answering and '
     'service-guidance system based on **Retrieval-Augmented Generation (RAG)**. '
     'The system adopts',
     'this paper designs and implements **ZhengMingBai (GovRAG)**, an intelligent '
     'question-answering and service-guidance system based on '
     '**Retrieval-Augmented Generation (RAG)**. The system adopts'),
    # 1.3 研究对象
    ('本文以自主实现的"政务智能问答与办事引导系统"为研究对象',
     '本文以自主实现的「政明白（GovRAG）」政务问答系统为研究对象'),
    # 3.1 目标段
    ('本研究的目标是构建一个能够依据政务办事指南回答办事咨询，并在依据缺失时明确拒答的问答系统。',
     '本研究的目标是构建「政明白（GovRAG）」——一个能够依据政务办事指南回答办事咨询，'
     '并在依据缺失时明确拒答的问答系统。'),
    # 5 结论首段
    ('设计并实现了一套基于检索增强生成的政务智能问答与办事引导系统，并在',
     '设计并实现了一套基于检索增强生成的政务问答系统「政明白（GovRAG）」，并在'),
    # 关键词补充
    ('**关键词：** 检索增强生成；政务服务；混合检索；幻觉抑制；相关性闸门；智能问答',
     '**关键词：** 检索增强生成；政务服务；混合检索；幻觉抑制；相关性闸门；智能问答；政明白（GovRAG）'),
]

for old, new in pairs:
    assert old in t, f"未找到：{old[:50]}"
    t = t.replace(old, new)

# 统一引号风格（论文正文内的系统名）
t = t.replace('"政明白（GovRAG）"', '「政明白（GovRAG）」')

NEW.write_text(t, encoding="utf-8")
OLD.unlink()
print("OK ->", NEW)
