"""文本处理工具：清洗、分块、输入过滤（离线预处理模块复用）。"""
from __future__ import annotations

import re
import unicodedata

# 常见页眉页脚模式
_HEADER_PATTERNS = [
    # 必须出现"页"或"N / 共 M"这类页码特征。
    # 早期写法把 第? / 页? 都设为可选，退化成"匹配任意纯数字行"，
    # 会把事项编码（如 5442106041002）当页眉删掉，造成检索盲区。
    re.compile(r"^\s*第\s*[0-9一二三四五六七八九十百千]+\s*页\s*$"),
    re.compile(r"^\s*[0-9]+\s*/\s*共?\s*[0-9]+\s*页?\s*$"),
    re.compile(r"^\s*[-—]{2,}\s*[0-9]+\s*[-—]{2,}\s*$"),
    re.compile(r"^\s*[-—_.·]{3,}\s*[0-9]+\s*[-—_.·]{3,}\s*$"),
    re.compile(r"^\s*(页眉|页脚|内部资料|仅供参考)\s*[:：]?\s*$"),
]

_CTRL_CHARS = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
_MULTI_SPACE = re.compile(r"[ \t\u00a0]+")
_MULTI_NL = re.compile(r"\n{3,}")
_URL = re.compile(r"https?://\S+")

# ---- "跨域通办" 区块（新版办事指南才有，事项版本 4+）----
# 它会把全国/全省所有市、区、县、镇的名字逐个列出来，动辄上千字。
# 这是典型的"关键词磁铁"：只要问题里出现任何地名（"广州怎么办""深圳社保"），
# 就会命中这篇文档，把真正相关的事项挤下去。旧版指南没有这一段，
# 所以只有新抓的语料才会带进来。区块从独立成行的"跨域通办"开始，
# 到下一个标准章节名为止。
_SKIP_BLOCK_START = "跨域通办"
_BLOCK_END_MARKERS = frozenset((
    "基础信息", "审批信息", "受理范围", "受理条件", "材料清单",
    "网上办理流程", "线下办理流程", "办理流程", "收费标准", "收费信息",
    "实施依据", "设定依据", "咨询方式", "申请材料", "办理时限",
))
# 兜底：万一没有遇到结束标志，最多跳这么多行就恢复，避免把整篇文档吃掉
_SKIP_BLOCK_MAX_LINES = 400


# NFKC 归一化会把全角标点转成半角，需先保护中文标点再还原
_CJK_PUNCT = "，。；：！？、（）《》【】“‘’”…—"
_PUNCT_MAP = {c: chr(0xE000 + i) for i, c in enumerate(_CJK_PUNCT)}


def clean_text(text: str) -> str:
    """文本清洗：去除页眉页脚、控制字符、多余空白与重复行。"""
    if not text:
        return ""
    for c, ph in _PUNCT_MAP.items():
        text = text.replace(c, ph)
    text = unicodedata.normalize("NFKC", text)
    for c, ph in _PUNCT_MAP.items():
        text = text.replace(ph, c)
    text = _CTRL_CHARS.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines: list[str] = []
    skipping = 0
    for raw in text.split("\n"):
        line = _MULTI_SPACE.sub(" ", raw).strip()
        # 页眉页脚 / 空行
        if not line:
            continue
        if skipping:
            # 跳过"跨域通办"区块，直到下一个标准章节名
            if line in _BLOCK_END_MARKERS:
                skipping = 0
            elif skipping >= _SKIP_BLOCK_MAX_LINES:
                skipping = 0
            else:
                skipping += 1
                continue
        if line == _SKIP_BLOCK_START:
            skipping = 1
            continue
        if any(p.match(line) for p in _HEADER_PATTERNS):
            continue
        # 连续重复行去重（PDF 解析常见噪声）。
        # 注意只对"紧邻上一行"去重：政务表单里"否""无"这类短值会合法地重复出现，
        # 早期按"全文出现过的短行"去重会把它们误删。
        if lines and lines[-1] == line and len(line) < 60:
            continue
        lines.append(line)

    text = "\n".join(lines)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# 政务办事指南的标准章节名。语料来自 PDF 表格抽取，章节名是**独立成行的裸文本**，
# 没有 Markdown 的 `#` 前缀 —— 只认 `#` 的话这些文档会被当成"无章节"整篇切分，
# 导致：上下文头缺章节名、enrich_sections 无法定向召回、rerank 的章节意图加权全部失效。
# 名单以"原 RAG 管道产出的真实章节集合"为准，不要凭感觉加词：
# 早期版本混入了"其他信息""办理窗口""审批服务形式"，它们其实是**材料表的列名**
# （材料名称/材料依据/材料形式/材料要求/材料下载/其他信息），
# 一旦当成分界点，"材料清单"章节会被截成只剩 24 字的表头。
_GOV_SECTION_NAMES: tuple[str, ...] = (
    "网上办理流程", "线下办理流程", "受理范围", "受理条件", "材料清单",
    "办理流程", "收费标准", "收费信息", "实施依据", "设定依据",
    "咨询方式", "审批信息", "基础信息",
    # 2026-09 扩语料时补入：新增 20 篇指南都带"常见问题/温馨提示"，
    # 不加进来它们会被并进上一个章节（咨询方式），上下文头就标错了章节名，
    # 而且 material 的"温馨提示"抽取（_SECTION_MAP.tips）根本匹配不到。
    # 已确认旧 12 篇语料里没有这两个独立成行的词，不会影响原有分块。
    "常见问题", "温馨提示",
)
_PLAIN_SECTION_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(s) for s in _GOV_SECTION_NAMES) + r")\s*$", re.M
)
_MD_HEADING_RE = re.compile(r"^(#{1,4})\s*(.+?)\s*$", re.M)


def split_sections(text: str) -> list[tuple[str, str]]:
    """按 Markdown / 中文标题切分章节，返回 [(章节名, 正文)]。

    优先用 Markdown 标题；没有时回退到政务文档的"裸行章节名"，
    两者都没有才当作单章节整篇返回。
    """
    matches = list(_MD_HEADING_RE.finditer(text))
    title_group = 2
    if not matches:
        matches = list(_PLAIN_SECTION_RE.finditer(text))
        title_group = 1
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        head = text[: matches[0].start()].strip()
        if head:
            sections.append(("", head))

    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(title_group).strip()
        body = text[start:end].strip()
        if body:
            sections.append((title, body))
    return sections or [("", text)]


def chunk_text(text: str, size: int = 500, overlap: int = 100) -> list[str]:
    """按字数切分，优先在句号/换行处断开，保留重叠窗口。"""
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(start + size, n)
        if end < n:
            # 在窗口后半段寻找自然断点
            window = text[start:end]
            cut = -1
            for sep in ("\n\n", "\n", "。", "；", "！", "？", ". "):
                idx = window.rfind(sep, int(size * 0.5))
                if idx > cut:
                    cut = idx
            if cut > 0:
                end = start + cut + len(sep)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def sanitize_question(q: str, max_len: int = 1000) -> str:
    """输入过滤：去除控制字符、压缩空白、截断超长输入。"""
    if not q:
        return ""
    q = _CTRL_CHARS.sub("", str(q))
    q = _URL.sub("", q)
    q = _MULTI_SPACE.sub(" ", q).strip()
    q = re.sub(r"(.)\1{20,}", r"\1", q)  # 抑制刷屏字符
    if len(q) > max_len:
        q = q[:max_len]
    return q


def make_snippet(text: str, limit: int = 120) -> str:
    """生成摘要片段，用于答案溯源展示。"""
    t = _MULTI_SPACE.sub(" ", text.replace("\n", " ")).strip()
    return t if len(t) <= limit else t[:limit] + "…"
