"""材料抽取单元测试。

这是全项目最容易回归的地方：政务 PDF 会把一个表格单元格拆成多行，
抽取逻辑依赖「行号 -> 名称行缓冲 -> 标记行收口」，任何顺序调整都会静默破坏结果。
"""
from app.services.material import (
    _extract_rows,
    _is_noise,
    _is_table,
    _parse_line,
    _valid_step,
    body_of,
    extract_material,
)
from app.services.vectorstore import Hit

# 模拟 PDF 抽取后的材料表：单元格被拆成一行一个
PDF_MATERIAL_BODY = """材料名称
材料形式
1
个体工商户登
记（备案）申
请书
原件：1
纸质/电子化
2
经营场所证明
原件：1
纸质"""


class TestIsNoise:
    def test_column_headers_are_noise(self):
        for s in ("材料名称", "材料形式", "其他信息", "材料下载"):
            assert _is_noise(s), s

    def test_field_with_colon_is_noise(self):
        assert _is_noise("原件：1")

    def test_placeholder_values_are_noise(self):
        for s in ("无", "否", "是", "暂无", "中介服务"):
            assert _is_noise(s), s

    def test_empty_and_too_long(self):
        assert _is_noise("")
        assert _is_noise("啊" * 61)

    def test_image_hash_and_filename_are_noise(self):
        assert _is_noise("1b2c3d4e-1234")
        assert _is_noise("photo.png")

    def test_real_material_names_kept(self):
        # 注意：PDF 会把材料名拆成很短的行，所以这里**不能**做最小长度判断
        for s in ("身份证原件", "个体工商户登记（备案）申请书", "经营场所证明"):
            assert not _is_noise(s), s


class TestIsTable:
    def test_two_signals_mean_table(self):
        assert _is_table("原件：1\n复印件：0")

    def test_single_signal_is_not_table(self):
        assert not _is_table("原件：1")

    def test_empty(self):
        assert not _is_table("")


class TestParseLine:
    def test_pipe_separated(self):
        item = _parse_line("居民身份证 | 正反面复印 | 1份")
        assert item.name == "居民身份证"
        assert item.desc == "正反面复印"
        assert item.count == "1份"

    def test_leading_order_stripped(self):
        assert _parse_line("1. 营业执照").name == "营业执照"

    def test_trailing_parenthesis_becomes_desc(self):
        item = _parse_line("居民身份证（正反面复印）")
        assert item.name == "居民身份证"
        assert item.desc == "正反面复印"


class TestExtractRows:
    def test_reconstructs_split_cells(self):
        items = _extract_rows(PDF_MATERIAL_BODY)
        names = [i.name for i in items]
        assert names == ["个体工商户登记（备案）申请书", "经营场所证明"]

    def test_reads_count_from_marker_row(self):
        items = _extract_rows(PDF_MATERIAL_BODY)
        assert all(i.count == "1份" for i in items)

    def test_prose_without_row_numbers_yields_nothing(self):
        """没有行号开头的内容是字段说明块，不能当成材料名。"""
        body = "办理流程如下\n申请人提交材料\n窗口受理并审核"
        assert _extract_rows(body) == []

    def test_fragments_before_first_row_number_dropped(self):
        """行号之前的残片（如"请表格文书"）必须丢弃。"""
        body = "申请表格文书\n1\n营业执照\n原件：1"
        assert [i.name for i in _extract_rows(body)] == ["营业执照"]


class TestValidStep:
    def test_field_name_is_not_a_step(self):
        assert not _valid_step("服务对象")

    def test_too_short_is_not_a_step(self):
        assert not _valid_step("受理")

    def test_normal_step_kept(self):
        assert _valid_step("申请人通过广东政务服务网提交材料并等待审核")


class TestBodyOf:
    def test_strips_context_header(self):
        hit = Hit(
            text="个体工商户设立登记\n材料清单\n身份证原件1份",
            doc_name="个体工商户设立登记",
            section="材料清单",
        )
        assert body_of(hit) == "身份证原件1份"

    def test_no_header_kept_intact(self):
        hit = Hit(text="身份证原件1份", doc_name="X", section="材料清单")
        assert body_of(hit) == "身份证原件1份"


class TestExtractMaterial:
    def _hit(self, doc_name, section, text):
        return Hit(text=text, doc_id="GD01", doc_name=doc_name, section=section, score=0.9)

    def test_material_section_produces_list(self):
        hit = self._hit("个体工商户设立登记", "材料清单", PDF_MATERIAL_BODY)
        m = extract_material([hit])
        assert m is not None
        assert m["title"] == "个体工商户设立登记"
        assert [i["name"] for i in m["required"]] == [
            "个体工商户登记（备案）申请书",
            "经营场所证明",
        ]

    def test_basis_section_never_yields_materials(self):
        """依据章节里也会出现"原件："字样，不能当成材料表。"""
        body = "《个体工商户条例》\n原件：1\n复印件：0"
        hit = self._hit("个体工商户设立登记", "实施依据", body)
        assert extract_material([hit]) is None

    def test_empty_hits(self):
        assert extract_material([]) is None
