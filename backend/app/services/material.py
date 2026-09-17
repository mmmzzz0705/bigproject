"""从检索片段中抽取结构化办事材料清单（大模型不可用时的确定性兜底方案）。"""
from __future__ import annotations

import re

from ..schemas import MaterialItem
from ..utils.text import make_snippet
from .vectorstore import Hit

# 章节名关键字 -> 字段
_SECTION_MAP = {
    "department": ("受理部门", "承办部门", "主管部门", "实施主体"),
    "legal_time": ("承诺时限", "办理时限", "法定时限", "承诺办结时限"),
    "fee": ("收费标准", "收费依据", "是否收费", "收费信息"),
    "channel": ("办理渠道", "办理地点", "办理方式"),
    "tips": ("温馨提示", "注意事项", "特别提醒"),
}

_COUNT_RE = re.compile(r"(\d+\s*(?:份|张|个|页|次))")

# 基础信息表格中的字段名 -> 结构化字段（PDF 抽取语料用「键 值」成对成行）
_KV_MAP = (
    ("department", ("实施主体", "受理部门", "承办部门", "主管部门", "委托部门")),
    ("legal_time", ("承诺办结时限", "承诺时限", "法定办结时限", "法定时限")),
    ("fee", ("是否收费", "收费标准", "收费依据")),
    ("channel", ("办理地点", "办理渠道", "办理形式", "窗口办理")),
)

_JUNK_VALUE = ("无", "否", "是", "", "暂无")


def _match_section(section: str, keywords: tuple[str, ...]) -> bool:
    return any(k in section for k in keywords)


def body_of(hit: Hit) -> str:
    """去掉检索文本前追加的"文档标题/章节"上下文头，还原正文。"""
    lines = (hit.text or "").split("\n")
    idx = 0
    for expected in (hit.doc_name, hit.section):
        if expected and idx < len(lines) and lines[idx].strip() == expected:
            idx += 1
    return "\n".join(lines[idx:]).strip()


# 表头 / 噪声行：不应作为材料名称
_NOISE_NAME = re.compile(
    r"^(?:名称|类型|材料名称|材料依据|材料形式|材料要求|材料下载|材料类型|其他信息|"
    r"纸质材料规格|是否免提交|填报须知|示例样本|空白表格|已关联电子证照|原件|复印件|"
    r"必要|非必要|纸质|电子化|证照|其他|份数|页数|来源渠道|备注|说明|"
    r"无|否|是|暂无|中介服务)$"
)
# 图片哈希 / 纯符号行
_HASH_LIKE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?", re.I)


# 字段名 / 提示语：出现在"材料名"里说明抽错了
_NOT_A_NAME = (
    "地方特色主题分类", "事项主题分类", "表示该材料", "中介服务", "备注信息",
    "服务对象", "受理范围", "面向自然人", "面向法人", "已关联电子证照",
)


def _is_noise(name: str) -> bool:
    """判断字符串是否"不是材料名"。

    注意：这里不做最小长度判断——PDF 会把材料名拆成 "个体工商户登"/"记（备案）申"/"请书"
    这样的短行，最小长度只在拼接完成后（flush）校验。
    """
    n = (name or "").strip()
    if not n or len(n) > 60:
        return True
    if "：" in n or ":" in n:          # 材料名不应带冒号（那是字段名）
        return True
    if any(k in n for k in _NOT_A_NAME):
        return True
    if _NOISE_NAME.match(n):
        return True
    if n.isdigit() or re.fullmatch(r"[\d\W_]+", n):
        return True
    if _HASH_LIKE.match(n) or n.endswith((".png", ".jpg", ".pdf", ".jpeg")):
        return True
    return False


def _parse_line(line: str) -> MaterialItem:
    """解析材料行：支持 `名称 | 说明 | 份数`、`名称（说明）`、`1. 名称` 等写法。"""
    raw = re.sub(r"^\s*([-*•]|\d+[.、)])\s*", "", line).strip()
    if not raw:
        return MaterialItem(name="")

    name, desc, count = raw, "", ""
    for sep in ("|", "｜"):
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep)]
            # 去掉前导序号列（PDF 表格常见： "1 | 营业执照 | 证照"）
            while parts and (parts[0].isdigit() or not parts[0]):
                parts.pop(0)
            if not parts:
                return MaterialItem(name="")
            name = parts[0]
            for p in parts[1:]:
                if _COUNT_RE.fullmatch(p):
                    count = p
                elif not desc and not _is_noise(p):
                    desc = p
            return MaterialItem(name=name, desc=desc, count=count)

    # 尾部份数，如 "居民身份证原件 1 份"
    m = _COUNT_RE.search(raw)
    if m and len(raw) - m.end() <= 2:
        count = m.group(1)
        raw = raw[: m.start()].strip()

    # 括号说明，如 "居民身份证（正反面复印）"
    m = re.search(r"[（(]([^（）()]+)[）)]\s*$", raw)
    if m:
        desc = m.group(1).strip()
        raw = raw[: m.start()].strip()

    return MaterialItem(name=raw.strip(" ：:；;"), desc=desc, count=count)


def _lines(body: str) -> list[str]:
    out = []
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


# ---- 政务 PDF 抽取语料的材料表：行标记 / 噪声行 ----
# 出现这些行，说明上一行是「材料名称」的结尾（PDF 表格被拆成了一行一个单元格）
_ROW_MARKER = re.compile(
    r"^(原件|复印件|纸质|电子化|必要|非必要|已关联电子证照|该材料免提交|"
    r"材料类型|材料形式|来源渠道|是否免提交|纸质材料规格)"
)
# 表格列名 / 按钮 / 说明标题：清空缓冲，不作为材料名
_NOISE_ROW = re.compile(
    r"^(空白表格|示例样本|填报须知|其他要求|备注|说明|名称|类型|材料名称|材料依据|"
    r"材料形式|材料要求|材料下载|其他信息|序号|份数|页数|来源渠道|中介服务)$"
)
_COUNT_ROW = re.compile(r"^原件[：:]\s*(\d+)")
# 材料表整体特征：命中 >=2 次才认为该片段是材料表
_TABLE_SIGNAL = re.compile(r"原件[：:]|复印件[：:]|纸质/电子化|已关联电子证照|该材料免提交")

# 流程步骤的字段名噪声
_STEP_STOP = re.compile(
    r"^(服务对象|事项主题分类|面向自然人|面向法人|自然人|法人|其他主体|社会组织|"
    r"受理范围|办理地点|审批信息|基础信息|实施依据|其他信息|日常用语|事项类型)"
)


def _is_table(body: str) -> bool:
    return len(_TABLE_SIGNAL.findall(body or "")) >= 2


def _extract_rows(body: str) -> list[MaterialItem]:
    """从材料表中按「名称行 + 标记行」结构还原材料条目。

    PDF 抽取会把一个单元格拆成多行（如 "个体工商户登" / "记（备案）申" / "请书"），
    因此这里用缓冲拼接，遇到 原件：/复印件：/纸质/电子化 等标记行才收口。
    """
    lines = [l.strip() for l in (body or "").split("\n")]
    items: list[MaterialItem] = []
    buf: list[str] = []
    row_started = False   # 是否处于"行号开头"的材料行内（否则是字段说明块，应丢弃）

    def flush(end_idx: int) -> None:
        nonlocal buf
        if not buf:
            return
        name = "".join(buf).strip()
        buf = []
        if not row_started:
            return
        if not (3 <= len(name) <= 40) or _is_noise(name):
            return
        count = ""
        for nxt in lines[end_idx : end_idx + 7]:  # 含触发行本身（"原件：1" 常是收口行）
            m = _COUNT_ROW.match(nxt)
            if m:
                count = f"{m.group(1)}份"
                break
        items.append(MaterialItem(name=name, count=count))

    for i, s in enumerate(lines):
        if not s:
            continue
        bare = s.rstrip("：:；;，,。")
        if s.isdigit() or len(s) == 1:        # 行号 / 单字断行残片
            flush(i)
            row_started = s.isdigit()
            continue
        # 顺序要紧：先判列名噪声，再判"收口标记"，最后才用通用噪声规则，
        # 否则 "原件：1"（含冒号会被判为噪声）会先清空缓冲，导致材料名丢失。
        if _NOISE_ROW.match(bare):
            buf = []                           # 表格列名：丢弃缓冲
            continue
        if _ROW_MARKER.match(s):
            flush(i)                           # 收口：缓冲里的就是材料名
            row_started = False
            continue
        if _is_noise(s):
            buf = []
            continue
        buf.append(s)
        if len("".join(buf)) > 45:             # 过长说明是正文段落，不是材料名
            buf = []
    flush(len(lines))
    return items


# ---- 条目式材料清单（版式 B）----
# 并非所有办事指南都用"材料名称/原件：/复印件："的表格版式。实测 GD05《一次性创业资助申领》
# 的材料部分是一段编号散文："应提交材料：1.符合条件人员基本身份类证明。2.创业重点扶持对象
# 佐证材料。属返乡创业人员第一、三类的提供户口簿…"。表格式解析器（_extract_rows）对这种版式
# 一条也抽不出来，于是材料清单整段为 0 —— 而大模型一旦没吐出 JSON 结构化清单，
# 规则兜底同样拿不到东西，前端就只剩空表。因此这里补一个条目式解析器。
_ENTRY_HEAD = re.compile(r"^(应提交材料|需提交材料|提交材料|申请材料|所需材料|材料清单|提交以下材料)")
_ENTRY_STOP = re.compile(
    r"^(应核验信息|核验信息|申请程序|办理程序|注意事项|温馨提示|补贴标准|补贴对象|"
    r"补贴期限|申领期限|申领流程|收费标准|其他要求)"
)


def _extract_numbered(body: str) -> list[MaterialItem]:
    """从"应提交材料：1.…2.…"这类编号散文中还原材料条目。

    按整段文本处理而不是按行：PDF 抽取的换行位置与语义边界无关，
    "应提交材料"既可能在一行开头，也可能跟在一大串补贴说明之后。
    只取每个编号后的第一句 —— 后续句子通常是"属返乡创业人员第一、三类的提供户口簿"
    这类适用说明，混进来会让材料名变成一长串。
    """
    text = body or ""
    m = re.search(
        r"(应提交材料|需提交材料|提交材料|申请材料|所需材料|提交以下材料)\s*[：:]\s*", text
    )
    if not m:
        return []
    seg = text[m.end():]
    stop = re.search(
        r"(应核验信息|核验信息|申请程序|办理程序|注意事项|温馨提示|补贴标准|补贴对象|"
        r"补贴期限|申领期限|申领流程)",
        seg,
    )
    if stop:
        seg = seg[: stop.start()]

    parts = re.split(r"\b\d{1,2}\s*[.、．]\s*", seg)
    if len(parts) < 2:
        return []
    items: list[MaterialItem] = []
    for p in parts[1:]:
        # PDF 抽取会在词中间断行（"创业 / 重点扶持对象佐证材料"），先去掉所有空白再判断
        first = re.sub(r"\s+", "", re.split(r"[。；;]", p.strip())[0]).strip(" ：:；;，,。")
        # 以"、""（""，""月"等非词首字符开头的，多半是上一个编号的续句被切断的残片
        if not first or first[0] in "、（）()，,；;。.":
            continue
        if not (4 <= len(first) <= 40) or _is_noise(first):
            continue
        if all(first != x.name for x in items):
            items.append(MaterialItem(name=first))
        if len(items) >= 12:
            break
    return items


def _valid_step(line: str) -> bool:
    return 8 <= len(line) <= 90 and not _STEP_STOP.match(line) and not _is_noise(line)


# 政务办事指南常见字段名：用于判断"值"在哪里结束
FIELD_NAMES = frozenset(
    """事项名称 日常用语 事项类型 承诺办结时限 法定办结时限 到办事现场次数 必须现场办理原因
    办件类型 是否告知承诺制 实施主体 实施主体性质 是否进驻政务大厅 是否支持物流快递
    是否支持预约办理 在线预约地址 实施编码 业务办理项编码 办理形式 基本编码 联办机构
    行使层级 权力来源 审批服务形式 业务系统 通办类型 通办区域 通办形式 委托部门
    受理部门 承办部门 主管部门 服务对象 事项主题分类 地方特色主题分类 受理范围
    受理条件 办理条件 收费标准 收费依据 是否收费 收费项目信息 办理地点 办理渠道
    办理方式 咨询方式 监督方式 法律法规名称 依据文号 条款号 颁布机关 实施日期 条款内容
    设定依据 实施依据 审批信息 基础信息 其他信息""".split()
)


def _scan_kv(hits: list[Hit], result: dict) -> None:
    """从「基础信息/审批信息」表格中按 `键 / 值` 成对抽取事项要素。

    PDF 抽取语料里字段名与值各占一行，无法用章节名直接映射，故逐行扫描。
    """
    for h in hits:
        if not any(s in (h.section or "") for s in ("基础信息", "审批信息", "受理范围")):
            continue
        lines = _lines(body_of(h))
        for i, line in enumerate(lines):
            field = None
            for f, ks in _KV_MAP:
                if line in ks:
                    field = f
                    break
            if not field or result.get(field):
                continue
            vals: list[str] = []
            for nxt in lines[i + 1 : i + 4]:
                if nxt in FIELD_NAMES or len(nxt) > 45 or _is_noise(nxt):
                    break
                vals.append(nxt)
                joined = "".join(vals)
                if field == "department" and re.search(r"[局厅部委所站队署处]$", nxt):
                    break
                if field == "legal_time" and (")" in nxt or "）" in nxt):
                    break
                if field in ("fee", "channel") and len(joined) >= 2:
                    break
                if len(joined) >= 12:
                    break
            val = "".join(vals).strip()
            if not val or val in _JUNK_VALUE:
                continue
            if field == "fee":
                val = "不收费" if val.startswith("否") else val
            result[field] = val


def extract_material(hits: list[Hit]) -> dict | None:
    """按章节关键字从 Top-K 片段中抽取材料清单。"""
    if not hits:
        return None

    best = hits[0]
    result: dict = {
        "title": best.doc_name or "",
        "department": "",
        "legal_time": "",
        "fee": "",
        "channel": "",
        "required": [],
        "optional": [],
        "steps": [],
        "tips": [],
    }

    for h in hits:
        sec = h.section or ""
        body = body_of(h)

        for field, keys in _SECTION_MAP.items():
            if not result[field] and _match_section(sec, keys):
                if field == "tips":
                    result["tips"] = [
                        _parse_line(l).name for l in _lines(body) if not _is_noise(_parse_line(l).name)
                    ]
                else:
                    result[field] = _lines(body)[0] if _lines(body) else body.strip()
                break

        # 材料：优先按"章节名"，其次按"正文是否是材料表"判断（章节标题常被 PDF 表格污染）
        # 但流程/依据类章节里也会出现"原件："字样，不能当作材料表，否则抽出审查标准之类的噪声
        is_material_sec = any(k in sec for k in ("必备材料", "必需材料", "申请材料", "材料清单"))
        not_material_sec = any(
            k in sec for k in ("办理流程", "实施依据", "设定依据", "受理条件", "受理范围",
                               "基础信息", "审批信息", "咨询方式", "收费信息")
        )
        if is_material_sec or (_is_table(body) and not not_material_sec):
            rows = _extract_rows(body)
            if not rows and is_material_sec:
                # 表格式版式没抽到任何东西 —— 可能是"应提交材料：1.…2.…"的条目式版式
                rows = _extract_numbered(body)
            for item in rows:
                if all(item.name != x.name for x in result["required"]):
                    result["required"].append(item)
        elif any(k in sec for k in ("可选材料", "补充材料", "免提交材料")):
            for item in _extract_rows(body):
                if all(item.name != x.name for x in result["optional"]):
                    result["optional"].append(item)
        elif "办理流程" in sec or "办理步骤" in sec:
            for l in _lines(body):
                if _valid_step(l) and l not in result["steps"]:
                    result["steps"].append(l)

    _scan_kv(hits, result)

    has_content = any([result["required"], result["optional"], result["steps"]])
    if not has_content:
        return None

    result["required"] = [i.model_dump() for i in result["required"]]
    result["optional"] = [i.model_dump() for i in result["optional"]]
    return result


def build_sources(hits: list[Hit], limit: int = 120) -> list[dict]:
    """构造答案溯源信息。

    跳过 `meta["aux"]` 的辅助片段：它们只是材料表补齐的中间产物，
    同章节同文档地重复出现在溯源里只会刷屏（表现为"问什么都是同一篇的七八条"）。
    """
    return [
        {
            "doc_name": h.doc_name,
            "section": h.section,
            "snippet": make_snippet(body_of(h), limit),
            "score": round(float(h.score), 4),
        }
        for h in hits
        if not h.meta.get("aux")
    ]
