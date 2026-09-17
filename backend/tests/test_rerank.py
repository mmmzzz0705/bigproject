"""重排（rerank）单元测试。

两个必须守住的性质：
1. 同一文档内，意图命中的章节要压过"关键词磁铁"式的依据章节；
2. **文档之间的顺序不能被重排改变** —— enrich_sections 用 hits[0] 当主文档，
   一旦顺序翻转，材料清单就会取自错误的文档。
"""
from app.services.rag import (
    RAGService,
    _material_chunk_score,
    _prefer,
    expand_query,
)
from app.services.vectorstore import Hit


def mk(doc_id: str, doc_name: str, section: str, score: float) -> Hit:
    return Hit(text="", doc_id=doc_id, doc_name=doc_name, section=section, score=score)


class TestRerank:
    def test_empty(self):
        assert RAGService._rerank([], "需要什么材料") == []

    def test_within_doc_material_beats_basis(self):
        hits = [mk("A", "文档A", "实施依据", 0.833), mk("A", "文档A", "材料清单", 0.80)]
        out = RAGService._rerank(hits, "办理这个业务需要什么材料")
        assert out[0].section == "材料清单"

    def test_score_never_exceeds_one(self):
        """乘算会超过 1，溯源里出现 1.08 的"相似度"很怪。"""
        hits = [mk("A", "文档A", "材料清单", 0.80)]
        out = RAGService._rerank(hits, "需要什么材料")
        assert out[0].score <= 1.0

    def test_doc_order_preserved_by_raw_score(self):
        """回归：全局按重排分排序会让主文档从 B 翻到 A。"""
        hits = [mk("A", "文档A", "实施依据", 0.833), mk("B", "文档B", "材料清单", 0.80)]
        out = RAGService._rerank(hits, "需要什么材料")
        assert [h.doc_id for h in out] == ["A", "B"]

    def test_basis_not_penalized_when_asked(self):
        hits = [mk("A", "文档A", "实施依据", 0.833)]
        out = RAGService._rerank(hits, "这个事项的实施依据是什么")
        assert out[0].score > 0.9          # 未乘 0.72 惩罚

    def test_basis_penalized_otherwise(self):
        hits = [mk("A", "文档A", "实施依据", 0.833)]
        out = RAGService._rerank(hits, "需要什么材料")
        assert out[0].score < 0.7

    def test_absolute_scores_untouched(self):
        """相关性闸门依赖绝对分，重排绝不能改它们。"""
        h = mk("A", "文档A", "实施依据", 0.833)
        h.vector_score, h.keyword_score = 0.81, 42.0
        RAGService._rerank([h], "需要什么材料")
        assert h.vector_score == 0.81
        assert h.keyword_score == 42.0


class TestPrefer:
    """同章节多片段时该用哪一段。

    材料清单章节动辄上万字，分数最高的常常是"填报须知"这类噪声段
    （含 原件/复印件 字样所以 _is_table 为真，但解析不出任何材料条目），
    结果就是"需要哪些材料"答出 0 条必备材料。
    """

    NOISE = "备注信息：仅通过网络开展经营活动的平台内经营者…受益所有人信息备案…"
    TABLE = "1\n《个体工商户登记（备案）申请书》\n原件：1\n复印件：0\n纸质/电子化\n必要"

    def _hit(self, text: str, section: str, score: float) -> Hit:
        return Hit(
            doc_id="d1", doc_name="个体工商户设立登记", text=text,
            section=section, score=score, vector_score=score, keyword_score=10.0,
        )

    def test_material_section_prefers_parsable_chunk_over_higher_score(self):
        noise = self._hit(self.NOISE, "材料清单", 0.95)
        table = self._hit(self.TABLE, "材料清单", 0.80)
        assert _prefer(table, noise) is table
        assert _prefer(noise, table) is table

    def test_non_material_section_uses_score(self):
        a = self._hit("承诺办结时限\n30", "基础信息", 0.70)
        b = self._hit("事项类型\n公共服务", "基础信息", 0.90)
        assert _prefer(a, b) is b
        assert _prefer(b, a) is b

    def test_material_section_falls_back_to_score_when_both_parsable(self):
        a = self._hit(self.TABLE, "材料清单", 0.70)
        b = self._hit(self.TABLE + "\n2\n经营者身份证\n原件：1", "材料清单", 0.90)
        assert _prefer(a, b) is b


class TestDocTieBreak:
    """两篇文档最高分打平时，用"佐证分"（多段召回）裁决。

    实测场景："办理个体工商户营业执照怎么办？"里，个体工商户注销登记与
    设立登记的最高分都是 0.821，注销仅靠顺序胜出，于是上下文全是注销内容，
    模型判定"资料没讲营业执照怎么办"，直接拒答。
    """

    def test_more_corroboration_wins_near_tie(self):
        hits = [
            mk("d1", "个体工商户注销登记", "材料清单", 0.821),
            mk("d2", "个体工商户设立登记", "受理条件", 0.820),
            mk("d2", "个体工商户设立登记", "材料清单", 0.469),
        ]
        out = RAGService._rerank(hits, "办理个体工商户营业执照怎么办？")
        assert out[0].doc_id == "d2"

    def test_clear_winner_is_not_disturbed(self):
        """差距明显时不能因为"佐证多"就翻盘。"""
        hits = [
            mk("d1", "甲", "材料清单", 0.95),
            mk("d2", "乙", "材料清单", 0.60),
            mk("d2", "乙", "受理条件", 0.58),
        ]
        out = RAGService._rerank(hits, "需要什么材料")
        assert out[0].doc_id == "d1"

    def test_exact_tie_prefers_corroboration(self):
        hits = [
            mk("d1", "甲", "材料清单", 0.80),
            mk("d2", "乙", "材料清单", 0.80),
            mk("d2", "乙", "受理条件", 0.70),
        ]
        out = RAGService._rerank(hits, "需要什么材料")
        assert out[0].doc_id == "d2"


class TestMaterialChunkScore:
    """材料片段评分：先看有没有"真材料表证据"，再看条目数。"""

    TABLE = "材料名称\n材料依据\n1\n《个体工商户登记（备案）申请书》\n原件：1\n复印件：0"
    NOISE = "备注信息：仅通过网络开展经营活动的平台内经营者…受益所有人信息备案…"

    def test_table_beats_noise(self):
        assert _material_chunk_score(self.TABLE) > _material_chunk_score(self.NOISE)

    def test_evidence_beats_row_count(self):
        """噪声段偶尔也能解析出 1 条似是而非的条目，但不能因此压过真表。"""
        noise_like = "1\n若因继承发生转移的，视以下两种情形提交材料\n原件：1"  # 带标记
        assert _material_chunk_score(noise_like)[0] == 1

    def test_more_rows_wins_when_both_are_tables(self):
        one = self.TABLE
        many = self.TABLE + "\n2\n经营者身份证\n原件：1\n复印件：0\n3\n经营场所证明\n原件：1"
        assert _material_chunk_score(many) > _material_chunk_score(one)

    def test_noise_without_evidence_scores_zero_on_first_field(self):
        assert _material_chunk_score(self.NOISE)[0] == 0


class TestExpandQuery:
    """查询扩展：口语 -> 语料术语。

    不扩展时"居住证到期了怎么续期"会被"申领居住证"抢走首位
    （语料里只有"签注"，没有"续期"这个词）。
    """

    def test_no_synonym_unchanged(self):
        q = "居住证怎么申领？"
        assert expand_query(q) == q

    def test_renewal_expanded_to_endorsement(self):
        for q in ("居住证到期了怎么续期？", "居住证过期了怎么办？", "居住证能延期吗？"):
            assert "签注" in expand_query(q)

    def test_transfer_expanded(self):
        assert "转移登记" in expand_query("房子过户怎么办？")

    def test_business_license_expanded(self):
        assert "设立登记" in expand_query("我想开店办个营业执照")

    def test_expansion_keeps_original_question(self):
        """扩展是追加不是替换，原问题必须完整保留。"""
        q = "居住证到期了怎么续期？"
        assert expand_query(q).startswith(q)
