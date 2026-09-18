"""RAG 核心链路：问题向量化 -> 向量检索 -> 上下文组装 -> 大模型生成。"""
from __future__ import annotations

import re
import threading

from ..config import settings
from ..schemas import MaterialList
from .llm import build_llm
from .material import _extract_rows, build_sources, extract_material
from .prompts import NO_HIT_ANSWER, RETRIEVAL_ERROR_ANSWER, VAGUE_GUIDE_ANSWER
from .vectorstore import Hit, get_embedding, get_vector_store

# 命中这些关键词说明是"办事办理类"问题，需要强化材料章节召回
MATERIAL_INTENT_KEYS = (
    "材料", "清单", "需要", "哪些", "准备", "流程", "步骤",
    "怎么办", "如何办", "怎么办理", "如何办理", "在哪办", "怎么",
)

# 触发"结构化字段定向召回"的意图词。
# 比 MATERIAL_INTENT_KEYS 更宽：时限/收费/条件/部门/依据 这些要素同样躺在
# 基础信息 / 审批信息 / 受理条件 等章节里，靠通用检索常常捞不到具体那一段
# （实测问"承诺多少个工作日办结"，Top-4 全是审批信息但都不含"承诺办结时限"）。
# 早期只按 MATERIAL_INTENT_KEYS 判断，导致这类问题永远不做章节补全。
STRUCTURED_INTENT_KEYS = MATERIAL_INTENT_KEYS + (
    "时限", "多久", "几天", "工作日", "办结", "什么时候",
    "收费", "多少钱", "费用", "要钱吗", "免费",
    "条件", "资格", "能不能", "符合",
    "部门", "哪里办", "在哪", "哪个部门", "地址", "窗口", "咨询",
    "依据", "法规", "条例", "文号",
    # 办理类口语。早期只认"怎么办/需要/材料"，像"不想开了要办什么登记"
    # 这种说法一个都不命中，于是完全不做章节补全，回答只能给出事项名，
    # 材料清单和流程全是空的（实测"个体工商户不想开了要办什么登记"）。
    "办什么", "要办", "办理", "办哪些", "手续", "申请", "申领", "登记",
)

# 结构化字段所在章节：定向召回以补全材料清单与事项要素
# 覆盖两套语料：示例 Markdown 文档 + 广东政务服务网 PDF 抽取语料
STRUCTURED_SECTIONS = (
    "必备材料",
    "可选材料",
    "材料清单",
    "材料名称",
    "办理流程",
    "网上办理流程",
    "线下办理流程",
    "基础信息",
    "审批信息",
    "受理条件",
    "受理范围",
    "受理部门",
    "承诺时限",
    "收费标准",
    "收费信息",
    "办理渠道",
    "注意事项",
    "温馨提示",
)

# ---- 重排（rerank）规则：按问题意图给不同章节加权 ----
# 依据类章节（实施依据/设定依据）会大段罗列法律法规名称（…条例/…办法/…规定），
# 是典型的"关键词磁铁"：不管问什么政务问题，它的 BM25 和向量分都很高，
# 会把真正有用的 材料清单/办理流程 挤到后面，导致"公积金""社保卡"这类问题
# 明明库里没有，却因为命中了某篇文档的"实施依据"而通过相关性闸门。
# 因此：命中意图的章节加权，未命中意图的依据类章节降权。
_SECTION_INTENT: tuple[tuple[tuple[str, ...], tuple[str, ...], float], ...] = (
    (("材料", "清单", "需要", "哪些", "准备", "带什么", "提交"),
     ("材料清单", "必备材料", "可选材料", "申请材料", "材料名称"), 1.35),
    (("流程", "步骤", "怎么办理", "如何办理", "怎么办", "如何办", "程序", "网上办"),
     ("办理流程", "网上办理流程", "线下办理流程", "审批信息"), 1.35),
    (("时限", "多久", "几天", "几个工作日", "什么时候", "办结"),
     ("基础信息", "审批信息", "办理流程", "承诺时限"), 1.22),
    (("收费", "多少钱", "费用", "要钱吗", "免费"),
     ("收费信息", "收费标准", "基础信息"), 1.30),
    (("条件", "资格", "能不能", "符合", "要求"),
     ("受理条件", "受理范围"), 1.30),
    (("部门", "哪里办", "在哪", "哪个部门", "地址", "窗口", "咨询"),
     ("受理部门", "咨询方式", "基础信息"), 1.30),
    (("依据", "根据", "法规", "条例", "文号", "政策文件"),
     ("实施依据", "设定依据"), 1.35),
)

_BASIS_SECTIONS = ("实施依据", "设定依据", "法律依据", "政策依据")
_RERANK_PENALTY = 0.72

# 查询扩展：老百姓口语 -> 语料术语。
# 语料写"签注"，群众说"续期/到期"；语料写"转移登记"，群众说"过户"。
# 不扩展时语义相近但字面不同，会把相似事项排错首位：
#   实测"居住证到期了怎么续期？"原本首选"申领居住证"(0.7166 vs 签注 0.7044)，
#   扩展后签注文档反超（0.7298 vs 0.7229）。
_QUERY_SYNONYMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("续期", "到期", "延期", "续签", "换证", "过期"), "签注"),
    (("过户", "二手房", "买卖房屋"), "转移登记"),
    (("营业执照", "开店", "开公司"), "设立登记"),
    # 群众说"改名字/更名"，语料写"变更登记"。不扩展时字面零重叠，
    # 实测"我的店要改名字，需要办什么登记？"向量分仅 0.760、关键词 9.4，
    # 两个通道都够不到闸门，整条链路被判成"域外"直接拒答。
    (("改名", "更名", "换名", "改字号", "换字号"), "变更登记"),
    # "不想开了/不干了/关门"说的是**注销**，但字面里的"开"会把语义拉向"设立登记"。
    # 1024 维模型实测："个体工商户不想开了要办什么登记？"Top-1 是设立登记 0.805、
    # 注销登记 0.774 —— 只差 0.03，语义模型自己分不开，必须靠字面同义词拉一把。
    (("不想开", "不开了", "不干了", "不经营", "关门", "歇业", "停业", "倒闭", "注销"), "注销登记"),
)


def expand_query(question: str) -> str:
    """追加同义词，同时作用于向量检索与 BM25（两个通道共用该字符串）。"""
    extra = [syn for keys, syn in _QUERY_SYNONYMS if any(k in question for k in keys)]
    return f"{question} {' '.join(extra)}".strip() if extra else question


# 业务实体词：问题里出现任意一个，说明群众点到了具体业务，可以按 Top-1 事项直接作答。
# 一个都不出现的（"怎么办证""请问怎么办理""帮我看看要带啥"）说明根本没说清要办什么，
# 此时硬答某一个事项必然答非所问 —— 实测"怎么办证"Top-1 是《居住证业务申办（补换领签注）》。
# 词表来自 12 篇入库指南的事项名，语料扩充时需要同步补。
# 注意：这份词表必须跟着语料一起扩。2026-09 语料从 12 篇扩到 32 篇后，
# "首次申领普通护照需要什么材料""教师资格认定需要什么材料"这种**明确问法**
# 因为词表里没有"护照""教师资格"，被 _is_vague 第一条件当成"没说清办什么"
# → 明明 Top1 就命中了正确文档，却退化成候选引导。新增语料后务必回来补词。
#
# ⚠️ 反向的坑同样存在（2026-09-15 实测）：词表只能放**知识库已收录**的事项词。
# 曾经把"低保""残疾"也写进来（当作通用政务词），而语料里根本没有这两项 ——
# 结果"残疾人证怎么办理？"因为命中了"残疾"，被 _is_vague 判成"说清了要办什么"，
# 直接按 Top-1《申领居住证》硬答，编造出一整套流程。
# 教训：词表是"我们有底气直接答的业务清单"，不是"政务词汇表"。
# 未收录事项的词写进来，等于给系统发了一张它兑现不了的许可证。
ENTITY_HINTS = (
    "居住证", "签注", "社保", "养老", "保险", "补贴", "资助", "创业", "就业", "失业",
    "退休", "工伤", "生育", "医疗", "医保", "公积金",
    "营业执照", "个体", "公司", "企业", "开店", "门市", "店铺", "店", "注销", "变更", "设立",
    "过户", "房屋", "房产", "不动产", "宅基地", "土地",
    "户籍", "户政", "身份证", "结婚", "结婚证", "离婚", "出生", "公证", "税务", "发票",
    # ---- 2026-09 扩语料补充 ----
    "护照", "港澳", "通行证", "出境", "入境",
    "教师资格", "资格认定", "老师", "教师", "公共场所", "卫生许可", "食品经营",
    # 注意：这里**故意不放**"许可证""登记""证"这类通用后缀。
    # 2026-09-15 实测：放了"许可证"之后，"烟草专卖零售许可证怎么办理？"
    # 因为命中该词被判成"说清了要办什么"，直接按 Top-1《食品经营许可证核发》
    # 硬答出一整套受理条件 —— 而语料里根本没有烟草专卖这一项。
    # 通用后缀对任何政务问法都成立，信息量为零，却能让未收录事项蒙混过关。
    "公租房", "保障房", "保障性住房", "租赁", "住房", "租房", "提取", "贷款",
    # ---- GD32 社保卡（2026-09-15 入库）----
    # 只放具体事项词；"卡"这种通用后缀不放（同"许可证"的教训）
    "社保卡", "社会保障卡", "一卡通", "制卡", "领卡",
    "驾驶证", "驾照", "换证", "机动车", "车牌", "上牌", "车辆",
    "异地就医", "就医", "备案", "转移接续", "入户", "落户", "户口", "人才引进",
)

_MATERIAL_SECTIONS = ("材料清单", "必备材料", "可选材料", "申请材料", "材料名称")

# 材料表的列名。只有章节开头那一段（表头 + 前几条材料）会同时出现这几个词，
# 后面的"填报须知/备注"段落不会。用它来定位"真正的材料表"比看行数可靠得多：
# 噪声段偶尔也能被解析出 1 条似是而非的条目（实测 GD01 抽出过"居所不一致的"）。
_MATERIAL_HEADER_HINT = ("材料名称", "材料依据", "材料形式", "材料要求")


def _material_chunk_score(text: str) -> tuple[int, int, int]:
    """材料片段打分，越大越像"真正的材料表"。

    依次比较：
      1. 是否有"原件：/复印件："收口标记 —— 真正的材料行必然带这个，
         噪声段（填报须知/备注）偶尔也能被解析出 1 条似是而非的条目
         （实测 GD09 抽出过"若因继承发生转移的，视以下两种情形提交材料"），
         所以先要求有真材料表的证据，把噪声挡在外面；
      2. 能解析出的条目数 —— 同样是真表，条目多的那一段信息量更大
         （早期把"表头命中数"排第一，结果专挑到章节开头那段只有 1 条的表头，
         反而比原来少抽了材料）；
      3. 表头命中数 —— 仅用于同分兜底。
    """
    header = sum(1 for k in _MATERIAL_HEADER_HINT if k in text)
    marks = sum(text.count(m) for m in ("原件：", "原件:", "复印件：", "复印件:"))
    return (1 if marks > 0 else 0, len(_extract_rows(text)), header)


def _prefer(a: Hit, b: Hit) -> Hit:
    """两个同章节片段里挑更该用的那个。

    材料类章节优先看"能不能解析出材料行"，而不是分数：
    分数最高的常常是填报须知这类噪声段，看着像材料表但没有一条可用条目。
    其他章节仍按分数取。
    """
    if any(s in a.section for s in _MATERIAL_SECTIONS):
        ra = bool(_extract_rows(a.text))
        rb = bool(_extract_rows(b.text))
        if ra != rb:
            return a if ra else b
    return a if a.score >= b.score else b


class RAGService:
    """检索增强问答服务（进程内单例）。"""

    _instance: "RAGService | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "RAGService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    # 必须先初始化完再发布：_init() 里的 get_vector_store()/build_llm()
                    # 都是耗时操作，若提前把实例挂到 cls._instance，并发的第二个线程
                    # 会在外层检查处拿到未初始化完的半成品（访问 svc.llm 直接 AttributeError）。
                    inst = super().__new__(cls)
                    inst._init()
                    cls._instance = inst  # 初始化失败时保持 None，下次调用可重试
        return cls._instance

    def _init(self) -> None:
        self.store = get_vector_store()
        self.embedding = get_embedding()
        self.llm = build_llm()
        print(f"[init] LLM provider = {self.llm.name}")

    # ---------------- 检索 ----------------
    def retrieve(self, question: str, top_k: int | None = None) -> list[Hit]:
        """问题向量化 + 混合检索（向量余弦 + BM25 关键词）+ 意图感知重排。"""
        if self.store.count() == 0:
            return []
        k = top_k or settings.TOP_K
        q = expand_query(question)
        vec = self.embedding.embed([q])[0]
        hits = self.store.search(vec, k, query_text=q)
        # 重排仍用原问题：扩展词是同义词不是意图词，混进去会干扰意图判定
        return self._rerank(hits, question)

    @staticmethod
    def _rerank(hits: list[Hit], question: str) -> list[Hit]:
        """意图感知重排：只调整融合分用于排序，不动向量/关键词绝对分。

        绝对分（vector_score / keyword_score）保持原值，
        相关性闸门 `_is_relevant` 的判定因此不受重排影响。
        """
        if not hits:
            return hits

        want_basis = any(k in question for k in ("依据", "法规", "条例", "文号", "根据"))

        for h in hits:
            # 保留原始融合分：文档级排序要用它，避免重排把"哪篇文档最相关"改掉
            h.meta["raw_score"] = h.score
            factor = 1.0
            for keys, sections, boost in _SECTION_INTENT:
                if any(k in question for k in keys) and any(s in h.section for s in sections):
                    factor *= boost
            # 依据类章节只在用户确实问"依据"时才该排前面
            if not want_basis and any(s in h.section for s in _BASIS_SECTIONS):
                factor *= _RERANK_PENALTY
            # 夹到 1 以内：乘算会超过 1，溯源里出现 1.08 的"相似度"很怪
            h.score = round(min(h.score * factor, 0.9999), 4)

        # 两级排序：先按文档的原始最高分定文档顺序，再按重排分定文档内章节顺序。
        # 只按重排分全局排序会让依据类降权**改变命中的是哪篇文档**，
        # 而 enrich_sections 用 hits[0] 当主文档，材料清单就会取自错误的文档
        # （实测"高校毕业生就业创业补贴"因此取到了"灵活就业社保补贴申领"的材料）。
        best_raw: dict[str, float] = {}
        # 文档级"佐证分"：该文档所有召回片段的原始分之和（近似，取前 3 段）。
        # 用于最高分打平时的裁决 —— 只比"最高分"会把"多段佐证"的文档和
        # "仅一段高分"的文档当成一样相关，而排序退化成看谁先出现。
        # 实测"办理个体工商户营业执照怎么办？"：个体工商户注销登记与设立登记
        # 最高分打平（都是 0.821），注销靠顺序胜出 -> 上下文全是注销内容 ->
        # 模型判定"资料没讲营业执照怎么办"，直接拒答。
        support: dict[str, float] = {}
        doc_scores: dict[str, list[float]] = {}
        for h in hits:
            raw = h.meta.get("raw_score", h.score)
            if raw > best_raw.get(h.doc_id, 0.0):
                best_raw[h.doc_id] = raw
            doc_scores.setdefault(h.doc_id, []).append(raw)
        for did, vals in doc_scores.items():
            support[did] = sum(sorted(vals, reverse=True)[:3])

        # 最高分差在 0.01 以内视为打平，此时改用佐证分裁决。
        # 用容差而不是严格相等：两个文档的最高分往往只差千分之几，
        # 严格相等几乎永远不触发，等于没做裁决。
        _TIE = 0.01
        top = max(best_raw.values(), default=0.0)
        leaders = [d for d, v in best_raw.items() if top - v <= _TIE]
        if len(leaders) > 1:
            # 只在并列者之间按佐证分重排，其余文档维持原状
            ranked = sorted(leaders, key=lambda d: -support.get(d, 0.0))
            for rank, did in enumerate(ranked):
                best_raw[did] = top - rank * 1e-6   # 微调，保证排序稳定且不改变量级

        hits.sort(key=lambda h: (-best_raw.get(h.doc_id, 0.0), -h.score))
        return hits

    def enrich_sections(self, hits: list[Hit], question: str, top_k: int | None = None) -> list[Hit]:
        """结构化字段补全：在已命中文档内定向召回要素章节。

        仅用于丰富材料清单，不参与相关性判定，因此必须在相关性过滤之后调用。
        """
        if not hits or not any(key in question for key in STRUCTURED_INTENT_KEYS):
            return hits

        k = top_k or settings.TOP_K
        primary = hits[0]
        section_q = f"{primary.doc_name} " + " ".join(STRUCTURED_SECTIONS)
        # 已经按 doc_filter 限定在同一篇文档内，池子取大一点代价很低，
        # 却能让"元素材表 / 承诺办结时限"这类靠后的片段进入候选。
        # 早期固定 16 条，GD04 的基础信息（含"承诺办结时限 30"）根本不在池里。
        pool_k = min(max(k * 8, 48), max(self.store.count(), 1))
        candidates = self.store.search(
            self.embedding.embed([section_q])[0],
            pool_k,
            query_text=section_q,
            doc_filter=primary.doc_id,
        )

        # 每个结构化章节只保留"最该被用到的那一段"。
        # 直接按分数取会出问题：材料清单章节长达上万字，分数最高的往往是
        # 填报须知/备注那段噪声（实测 GD01 取到了"受益所有人信息备案…备注信息…"，
        # 一个材料条目都解析不出来，最终必备材料为 0 条）。
        # 因此材料类章节改成"优先取真正能解析出材料行的片段"，分数只作次级判据。
        best_by_sec: dict[str, Hit] = {}
        for h in candidates:
            if h.section not in STRUCTURED_SECTIONS:
                continue
            cur = best_by_sec.get(h.section)
            best_by_sec[h.section] = h if cur is None else _prefer(h, cur)

        extra = sorted(best_by_sec.values(), key=lambda h: -h.score)[:8]

        # 补全片段的召回查询是"文档名 + 章节名"，与用户问题无关，
        # 得分天然偏高且对同一文档恒定 —— 不设上限的话溯源列表会被这几段刷屏，
        # 表现为"问什么都是 0.8794 / 0.8614 / 0.8506"。
        # 压到真实召回的最高分之下，保证真实命中始终排在前面。
        best = max((h.score for h in hits), default=0.0)
        if best > 0:
            cap = round(best * 0.999, 4)
            for h in extra:
                h.score = min(h.score, cap)

        merged = self._merge(hits, extra, limit=k + len(extra))
        return self._complete_material_chunks(merged, primary.doc_id, limit=2)

    def _complete_material_chunks(self, hits: list[Hit], doc_id: str, limit: int = 3) -> list[Hit]:
        """补齐材料表片段。

        为什么必须放在 merge **之后**：材料清单动辄被切成几十段，而
        search() 按 (doc_id, section) 去重，一个章节只会回来一条 ——
        回来的多半是"填报须知/备注"那段噪声，一条材料都解析不出来。
        噪声段还可能来自主召回（hits）而不是章节补全（extra），
        而 _merge 是"同章节保留高分"，补全片段被压过分之后根本挤不掉它
        （实测 GD07 就是这样：兄弟片段里明明有表头段，最终仍取到噪声段）。

        处理策略是"**只补不换**"，避免越修越差：
          · 原片段本身有真材料表证据（带"原件："）-> 保留，再把同章节里
            其他同样像材料表的片段补进来（材料表横跨多段，每段 500 字只装得下
            1~2 条，只看一段必然漏材料）；
          · 原片段没有证据（纯噪声段）-> 才用评分最高的兄弟片段替换掉它。
        """
        if not hits:
            return hits
        seen_sec: set[str] = set()
        for i, h in enumerate(hits):
            # 只补**主文档**：一次问答可能召回多篇相似事项（设立/变更/注销），
            # 若对每篇都补材料片段，噪声会把主文档真正有用的内容挤出上下文，
            # 模型反而判定"资料里没讲"，返回拒答（实测"办理个体工商户营业执照怎么办"
            # 就是这样被搞坏的：补进来 3 段注销登记的填报须知）。
            if h.doc_id != doc_id:
                continue
            if not any(k in h.section for k in _MATERIAL_SECTIONS) or h.section in seen_sec:
                continue
            seen_sec.add(h.section)
            siblings = self.store.fetch_section(doc_id, h.section)
            if not siblings:
                continue
            # 只认"像真材料表"的片段：带原件/复印件标记，且能解析出条目
            good = [s for s in siblings if _material_chunk_score(s.text)[0] and _material_chunk_score(s.text)[1] > 0]
            if not good:
                continue
            good.sort(key=lambda s: _material_chunk_score(s.text), reverse=True)

            if not _extract_rows(h.text):
                # 原片段一条都抽不出来（噪声段）：才替换成最好的那个。
                # 判据用"解析不出条目"而不是"没有原件标记"：部分文档的材料表
                # 本来就不用"原件：N"这套格式（如灵活就业社保补贴），
                # 按标记判会把它们误判成噪声。
                # 剩下的仍可补充
                best = good[0]
                hits[i] = Hit(
                    text=best.text,
                    doc_id=best.doc_id,
                    doc_name=best.doc_name,
                    section=best.section,
                    score=h.score,          # 沿用原位置的分，避免打乱溯源排序
                    meta=dict(best.meta),
                    vector_score=h.vector_score,
                    keyword_score=h.keyword_score,
                )
                have = {best.text}
            else:
                have = {h.text}

            added = 0
            for s in good:
                if s.text in have or added >= limit:
                    continue
                have.add(s.text)
                # 标记为辅助片段：只喂给 extract_material（抽取式兜底）用来补全材料清单，
                # **不进** build_context 的生成上下文，也不进溯源列表。
                # 这些片段多为"填报须知"式的表格附注，塞进上下文只会稀释有效信息。
                aux_meta = dict(s.meta)
                aux_meta["aux"] = True
                hits.append(
                    Hit(
                        text=s.text,
                        doc_id=s.doc_id,
                        doc_name=s.doc_name,
                        section=s.section,
                        score=h.score,
                        meta=aux_meta,
                        vector_score=h.vector_score,
                        keyword_score=h.keyword_score,
                    )
                )
                added += 1
        return hits

    # 泛问引导里"事项一句话说明"的取章节顺序
    _BRIEF_SECTIONS = ("基础信息", "受理范围", "事项名称")

    def _doc_brief(self, doc_id: str) -> str:
        """取该事项的一句话说明，用于引导列表；拿不到就返回空串（只列事项名）。

        语料是 PDF 抽取的，字段值被换行切得七零八落（"国有建设用地使用权及房\\n
        屋所有权登记"），所以先把整段压平再按"键 + 下一个键"截取字段值。
        """
        for sec in self._BRIEF_SECTIONS:
            try:
                rows = self.store.fetch_section(doc_id, sec, limit=2)
            except Exception:  # noqa: BLE001
                rows = []
            if not rows:
                continue
            flat = re.sub(r"\s+", "", "".join(r.text or "" for r in rows))
            parts: list[str] = []
            m = re.search(r"事项名称(.{2,40}?)(?:日常用语|事项类型|承诺办结|受理范围|$)", flat)
            if m and not m.group(1).startswith("无"):
                parts.append(m.group(1))
            m = re.search(r"实施主体(.{2,30}?)(?:实施主体性质|委托部门|是否进驻|$)", flat)
            if m:
                parts.append(m.group(1))
            if parts:
                return " · ".join(parts)[:56]
        return ""

    @staticmethod
    def _is_vague(question: str, top: Hit) -> bool:
        """判断是不是"没说清办什么"的泛问。

        两个信号：
          1. 问题里一个业务实体词都没有 —— 强信号，直接引导；
          2. 说到了业务，但语义分偏低（且没有术语强命中）—— 说明匹配到的
             事项仍然存疑，同样交给用户确认，比硬答一份材料清单稳妥。
        """
        if not any(k in question for k in ENTITY_HINTS):
            return True
        return (
            top.vector_score < settings.VAGUE_VECTOR_MAX
            and top.keyword_score < settings.KEYWORD_MIN_SCORE
        )

    def _guide_answer(self, hits: list[Hit]) -> dict:
        """泛问引导：问得太概括时列出最相近的候选事项，让用户确认而不是硬答一个。

        判据见 `answer()`：语义够得着（过了相关性闸门）但 Top-1 向量分偏低，
        说明问题里没说清"办哪一个"，此时直接给出某一事项的材料清单风险很高
        —— 实测"怎么办证"Top-1 是《申领居住证》，硬答就是答非所问。
        """
        docs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for h in hits:
            if h.doc_id in seen or not h.doc_name:
                continue
            seen.add(h.doc_id)
            docs.append((h.doc_name, self._doc_brief(h.doc_id)))
            if len(docs) >= 5:
                break
        if not docs:
            return {}
        items = "\n".join(
            f"{i}. 《{name}》" + (f" —— {brief}…" if brief else "")
            for i, (name, brief) in enumerate(docs, 1)
        )
        return {
            "answer": VAGUE_GUIDE_ANSWER.format(items=items),
            "material_list": None,
            "sources": build_sources(hits),
            "mode": self.llm.name,
            "hit": True,
        }

    def generate(self, question: str, history: list[tuple[str, str]], hits: list[Hit]) -> dict:
        """生成环节（可被子类覆盖以接入 LangChain 链）。"""
        return self.llm.answer(question, history, hits)

    def _fallback_answer(self, question: str, history: list[tuple[str, str]], hits: list[Hit]) -> dict:
        """大模型不可用时的兜底：用抽取式依据已召回片段作答。"""
        try:
            from .llm import ExtractiveLLM

            out = ExtractiveLLM().answer(question, history, hits)
            if (out.get("answer") or "").strip():
                out["answer"] += "\n\n> ⚠️ 当前大模型不可用，以上为依据知识库原文生成的兜底回答。"
                return out
        except Exception as e:  # noqa: BLE001
            print(f"[error] 抽取式兜底也失败：{e}")
        return {"answer": "", "material_list": extract_material(hits)}

    @staticmethod
    def _is_relevant(h: Hit) -> bool:
        """相关性判定：**以向量语义相似度为主判据**，关键词精确命中作兜底。

        为什么改成向量主导：口语化泛问（"我想开个小店，要办啥"）与语料术语字面
        几乎不重叠，BM25 接近 0，融合分被 0.55 的关键词项整体压低（实测 0.36），
        按旧口径一律判成"域外"直接拒答；而它的向量分有 0.79 —— 语义上确实就是
        "个体工商户设立登记"。检索侧按语义放行、生成侧再判断讲没讲清楚，
        比在门口就把群众挡回去更合理。
        """
        # 1) 语义主判据：向量余弦
        if h.vector_score >= settings.VECTOR_MIN_SCORE:
            return True
        # 2) 术语兜底：问题里出现政务术语（BM25 强命中）且融合分也够高。
        #    两个条件必须同时满足 —— 只看融合分的话，口语化泛问里那些
        #    "办/要/啥"的噪声关键词也能把不相关文档抬过线。
        return (
            h.keyword_score >= settings.KEYWORD_MIN_SCORE
            and h.score >= settings.FUSED_MIN_SCORE
        )

    @staticmethod
    def _merge(a: list[Hit], b: list[Hit], limit: int) -> list[Hit]:
        """按 (doc_id, section) 合并两路召回，同段保留高分。"""
        merged: dict[tuple[str, str], Hit] = {}
        for h in a + b:
            key = (h.doc_id, h.section)
            if key not in merged or h.score > merged[key].score:
                merged[key] = h
        return sorted(merged.values(), key=lambda x: -x.score)[:limit]

    # ---------------- 问答 ----------------
    def answer(self, question: str, history: list[tuple[str, str]] | None = None) -> dict:
        """完整 RAG 问答流程。"""
        # 1) 向量 + 关键词混合检索
        try:
            hits = self.retrieve(question)
        except Exception as e:  # noqa: BLE001
            # Embedding / 向量库瞬时故障（限流、网络抖动）时不要抛 500，
            # 也不要谎称"知识库没有该政策"——两者都会误导用户。
            print(f"[error] 检索失败：{e}")
            return {
                "answer": RETRIEVAL_ERROR_ANSWER,
                "material_list": None,
                "sources": [],
                "mode": self.llm.name,
                "hit": False,
            }

        # 2) 相关性过滤：低于阈值视为"知识库无该政策"，拒绝编造
        relevant = [h for h in hits if self._is_relevant(h)]
        if not relevant:
            # 先区分"库空"和"库没连上"：向量库初始化失败后会静默降级为空的内存库，
            # 此时检索必然为空。若照常回 NO_HIT_ANSWER，就是把服务故障说成
            # "知识库暂无该业务政策"，用户会误以为语料没入库（实测踩过）。
            if getattr(self.store, "degraded", False) or getattr(self.store, "load_error", ""):
                reason = getattr(self.store, "load_error", "") or "配置的向量库不可达"
                print(f"[error] 向量库不可用（{self.store.name}）：{reason}")
                return {
                    "answer": RETRIEVAL_ERROR_ANSWER,
                    "material_list": None,
                    "sources": [],
                    "mode": self.llm.name,
                    "hit": False,
                }
            return {
                "answer": NO_HIT_ANSWER,
                "material_list": None,
                "sources": [],
                "mode": self.llm.name,
                "hit": False,
            }

        # 2.5) 泛问引导：语义够得着、但问得太概括（Top-1 向量分偏低且没有术语强命中）
        #      —— 不硬答某一个事项，先列出候选让用户确认。
        #      实测"怎么办证"Top-1 是《申领居住证》，"我想开个小店要办啥"Top-1 是
        #      《个体工商户设立登记》，两者都不该直接甩一份材料清单给群众。
        top = relevant[0]
        if self._is_vague(question, top):
            guide = self._guide_answer(relevant)
            if guide:
                print(
                    f"[guide] 泛问引导：{question!r} -> top1={top.doc_name} "
                    f"vec={top.vector_score:.3f} kw={top.keyword_score:.2f}"
                )
                return guide

        # 3) 办事类问题：补全要素章节，保证材料清单字段完整
        #    补全要再调一次 Embedding，同样可能瞬时故障；失败就用未补全的结果继续，
        #    不要让它冒泡成 500。
        try:
            relevant = self.enrich_sections(relevant, question)
        except Exception as e:  # noqa: BLE001
            print(f"[error] 章节补全失败，使用未补全结果继续：{e}")

        try:
            # 4) 组装 Prompt 并调用大模型生成
            result = self.generate(question, history or [], relevant)
        except Exception as e:  # noqa: BLE001
            # 大模型调用失败（超时/限流/网络）：退化为抽取式，**仍然依据已召回片段作答**。
            # 注意：这里不能返回空答案，否则会被判成"知识库无该政策"，把超时误报成无结果。
            print(f"[error] 大模型调用失败，使用抽取式兜底：{e}")
            result = self._fallback_answer(question, history or [], relevant)

        answer = (result.get("answer") or "").strip() or NO_HIT_ANSWER
        material = result.get("material_list") or extract_material(relevant)

        # 大模型偶尔会漏输出 required 字段（长答案被截断或格式漂移），
        # 实测同一问题两次调用可能出现"必备 2 条"和"必备 0 条"。
        # 空清单对"需要哪些材料"这类问题是硬伤，因此用抽取式结果补齐。
        if material and not material.get("required"):
            fallback = extract_material(relevant)
            if fallback and fallback.get("required"):
                material["required"] = fallback["required"]
                if not material.get("optional") and fallback.get("optional"):
                    material["optional"] = fallback["optional"]

        # 结构校验，避免脏数据打到前端
        if material is not None:
            try:
                material = MaterialList(**material).model_dump()
            except Exception:  # noqa: BLE001
                material = None

        return {
            "answer": answer,
            "material_list": material,
            "sources": build_sources(relevant),
            "mode": self.llm.name,
            "hit": True,
        }
