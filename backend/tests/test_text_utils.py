"""文本工具单元测试：清洗、输入过滤、摘要、分块。"""
from app.utils.text import (
    chunk_text,
    clean_text,
    make_snippet,
    sanitize_question,
    split_sections,
)


class TestSanitizeQuestion:
    def test_empty(self):
        assert sanitize_question("") == ""
        assert sanitize_question(None) == ""

    def test_collapse_whitespace(self):
        # 只压缩空格/制表符，换行是有意保留的（问题可能是多行）
        assert sanitize_question("  社保卡  需要什么  ") == "社保卡 需要什么"
        assert sanitize_question("  社保卡\n怎么办  ") == "社保卡\n怎么办"

    def test_strip_control_chars(self):
        assert sanitize_question("社保卡\x00\x07怎么办") == "社保卡怎么办"

    def test_strip_url(self):
        q = "详情见 https://example.com/a?b=1 谢谢"
        assert "https://" not in sanitize_question(q)

    def test_max_len(self):
        # 不能用同一个字符重复：那样会先被"刷屏字符抑制"折叠掉，走不到截断
        q = "".join(str(i % 10) for i in range(5000))
        assert len(sanitize_question(q, max_len=100)) == 100

    def test_repeat_char_suppressed(self):
        assert sanitize_question("好" * 50) == "好"


class TestCleanText:
    def test_empty(self):
        assert clean_text("") == ""

    def test_removes_page_number(self):
        assert clean_text("正文内容\n第 3 页\n后续内容") == "正文内容\n后续内容"

    def test_cjk_punctuation_preserved(self):
        """NFKC 会把全角标点转成半角，必须还原。"""
        assert clean_text("办理时限：5个工作日，需提交材料。") == "办理时限：5个工作日，需提交材料。"

    def test_dedup_repeated_short_lines(self):
        text = "咨询服务电话\n咨询服务电话\n真实内容"
        assert clean_text(text) == "咨询服务电话\n真实内容"


class TestCleanTextNoOverStrip:
    """回归：清洗不能把正文里的数据行当噪声删掉。

    早期页眉正则把 `第?`/`页?` 都设为可选，退化成"匹配任意纯数字行"，
    导致事项业务编码（5442106041002）被删；去重又按"全文出现过的短行"
    判断，把政务表单里合法重复出现的 `否`/`无` 去重了。
    两者合计曾吃掉 28.7% 的正文（12 篇语料 382 片段 -> 修复后 534）。
    """

    def test_keeps_business_code_line(self):
        code = "5442106041002"
        assert code in clean_text(f"实施编码\n{code}\n实施机关")

    def test_keeps_bare_short_number(self):
        assert clean_text("承诺时限\n1\n工作日") == "承诺时限\n1\n工作日"

    def test_keeps_repeated_short_field_values(self):
        """非连续重复的短值是合法表单数据，不能去重。"""
        text = "是否收费：否\n办理形式：无\n是否收费：否"
        assert clean_text(text) == text

    def test_still_removes_real_page_numbers(self):
        assert clean_text("正文\n第 3 页\n后续") == "正文\n后续"
        assert clean_text("正文\n3 / 共 10 页\n后续") == "正文\n后续"

    def test_still_removes_consecutive_dupes(self):
        assert clean_text("咨询服务电话\n咨询服务电话\n真实") == "咨询服务电话\n真实"


class TestCleanTextCrossRegionBlock:
    """「跨域通办」区块必须整块删掉。

    新版办事指南（事项版本 4+）会把全国/全省所有市、区、县、镇名字逐个列出来，
    动辄上千字，是典型的"关键词磁铁"：问题里只要出现任何地名就会命中这篇文档。
    旧版指南没有这一段，所以只有新抓的语料才会带进来。
    """

    DOC = """签注居住证
基础信息
事项名称
签注居住证
跨域通办
通办类型
通办区域
通办形式
跨省通办
全部境内地区
全程网办
广州市、越秀区、海珠区、荔湾区、天河区
深圳市、罗湖区、福田区、南山区
佛山市、禅城区、南海区、顺德区
审批信息
行使层级
镇（乡、街道）级
材料清单
材料名称
1
居住证-签注居住证
原件：1
"""

    def test_block_is_removed(self):
        out = clean_text(self.DOC)
        assert "跨域通办" not in out
        assert "越秀区" not in out
        assert "南海区" not in out

    def test_surrounding_content_survives(self):
        out = clean_text(self.DOC)
        assert "事项名称" in out and "签注居住证" in out
        assert "审批信息" in out and "行使层级" in out
        assert "材料清单" in out and "原件：1" in out

    def test_block_ends_at_next_section(self):
        """必须停在下一个章节名，不能把后面的正文一起吃掉。"""
        out = clean_text(self.DOC)
        assert out.index("审批信息") < out.index("材料清单")

    def test_unterminated_block_does_not_eat_document(self):
        """没有结束标志时最多跳固定行数，不能吞掉整篇。"""
        doc = "基础信息\n跨域通办\n" + "\n".join(f"某市某区{i}" for i in range(600)) + "\n结尾标记"
        out = clean_text(doc)
        assert "结尾标记" in out

    def test_document_without_block_is_untouched(self):
        doc = "事项名称\n个体工商户设立登记\n审批信息\n行使层级\n县级\n"
        assert clean_text(doc) == doc.strip()


class TestMakeSnippet:
    def test_short_text_unchanged(self):
        assert make_snippet("很短的一句话") == "很短的一句话"

    def test_long_text_truncated(self):
        out = make_snippet("啊" * 300, limit=120)
        assert len(out) == 121          # 120 + 省略号
        assert out.endswith("…")

    def test_newline_flattened(self):
        assert make_snippet("第一行\n第二行") == "第一行 第二行"


class TestSplitSections:
    def test_no_heading(self):
        assert split_sections("只是一段正文") == [("", "只是一段正文")]

    def test_markdown_headings(self):
        text = "## 材料清单\n身份证\n## 办理流程\n第一步\n"
        secs = dict(split_sections(text))
        assert secs["材料清单"] == "身份证"
        assert secs["办理流程"] == "第一步"

    def test_plain_gov_section_names(self):
        """政务语料没有 Markdown 标题，章节名是独立成行的裸文本。

        只认 `#` 会让整篇文档被当成无章节，进而导致：
        上下文头缺章节名、enrich_sections 无法定向召回、rerank 章节加权失效。
        """
        text = "基础信息\n事项名称 申领居住证\n材料清单\n身份证\n受理条件\n年满16周岁"
        secs = dict(split_sections(text))
        assert secs["基础信息"] == "事项名称 申领居住证"
        assert secs["材料清单"] == "身份证"
        assert secs["受理条件"] == "年满16周岁"

    def test_subsection_preferred_over_parent(self):
        """网上/线下办理流程比"办理流程"更长，必须优先匹配长的。"""
        text = "办理流程\n总述\n网上办理流程\n第一步\n线下办理流程\n去窗口"
        assert [s for s, _ in split_sections(text)] == [
            "办理流程",
            "网上办理流程",
            "线下办理流程",
        ]

    def test_markdown_takes_priority(self):
        """有 Markdown 标题时按 Markdown 切，不再用裸行章节名二次切分。"""
        text = "## 材料清单\n身份证\n受理条件\n年满16周岁"
        secs = split_sections(text)
        assert len(secs) == 1
        assert secs[0][0] == "材料清单"
        assert "受理条件" in secs[0][1]

    def test_preamble_kept(self):
        text = "开头说明\n## 第一章\n正文"
        secs = split_sections(text)
        assert secs[0][0] == ""
        assert secs[0][1] == "开头说明"


class TestChunkText:
    def test_short_text_single_chunk(self):
        assert chunk_text("短文本", size=500, overlap=100) == ["短文本"]

    def test_chunks_cover_all_text(self):
        text = "".join(str(i % 10) for i in range(2000))
        chunks = chunk_text(text, size=500, overlap=100)
        assert len(chunks) > 3
        # 每块首尾都要在原文里出现，避免切出乱码或丢字
        for c in chunks:
            assert c[0] in text

    def test_respects_size(self):
        for c in chunk_text("字" * 2000, size=300, overlap=50):
            assert len(c) <= 300
