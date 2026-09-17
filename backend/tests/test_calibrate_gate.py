"""标定脚本的纯逻辑单测（不联网、不需要向量库）。

scripts/calibrate_gate.py 里的 recommend() 决定了闸门的绝对分阈值，
它一旦算错，表现是"域内问题被误杀"或"域外问题穿闸编造"——都很难在
运行时看出来。这里用构造数据把行为钉死。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "calibrate_gate.py"
_spec = importlib.util.spec_from_file_location("calibrate_gate", _SCRIPT)
assert _spec and _spec.loader
calibrate = importlib.util.module_from_spec(_spec)
sys.modules["calibrate_gate"] = calibrate
_spec.loader.exec_module(calibrate)

recommend = calibrate.recommend
recommend_pair = calibrate.recommend_pair


class TestRecommend:
    def test_separable_groups_find_zero_error_cut(self):
        """完全可分时，切点必须落在两组之间且零错分。"""
        pos = [0.80, 0.85, 0.90]
        neg = [0.20, 0.30, 0.40]
        t, err = recommend(pos, neg)
        assert err == 0
        assert 0.40 <= t <= 0.80

    def test_tight_margin_still_separates(self):
        """两组只差 0.01 时也要能找到零错分切点。"""
        pos = [0.50, 0.51]
        neg = [0.48, 0.49]
        t, err = recommend(pos, neg)
        assert err == 0
        assert 0.49 <= t <= 0.50

    def test_overlapping_groups_report_errors(self):
        """无法完全分开时，如实报告错分数，而不是假装为零。"""
        pos = [0.30, 0.80]
        neg = [0.50, 0.60]
        t, err = recommend(pos, neg)
        # 0.30 这个域内样本低于任何能挡住域外的切点，至少要错 1 条
        assert err >= 1
        assert t > 0.30

    def test_empty_input_is_safe(self):
        assert recommend([], [0.1, 0.2]) == (0.0, -1)
        assert recommend([0.8], []) == (0.0, -1)

    def test_single_value_groups(self):
        t, err = recommend([0.9], [0.1])
        assert err == 0
        assert 0.1 <= t <= 0.9

    @pytest.mark.parametrize("shift", [0.0, 0.25, 0.5])
    def test_scale_invariance(self, shift: float):
        """整体平移不改变可分性。"""
        pos = [0.7 + shift, 0.8 + shift]
        neg = [0.1 + shift, 0.2 + shift]
        _, err = recommend(pos, neg)
        assert err == 0


class TestRecommendPair:
    """闸门是「或」关系，联合标定必须按「或」语义计数。"""

    def test_or_semantics_blocks_keyword_only_outlier(self):
        """关键词分很高但语义无关 —— 独立看向量会漏判。

        neg 里 (vec=0.2, kw=90) 向量分很低，但关键词分极高。
        若只看向量分定阈值，它会因为 kw >= tk 照样穿闸。
        """
        pos = [(0.90, 30.0), (0.85, 40.0)]
        neg = [(0.20, 90.0), (0.30, 10.0)]
        tv, tk, err = recommend_pair(pos, neg)
        assert err == 0, (tv, tk, err)
        # 必须把关键词阈值抬到 90 以上，否则 neg[0] 会从关键词通道漏进来
        assert tk > 90.0
        assert tv <= 0.85

    def test_or_semantics_blocks_vector_only_outlier(self):
        """反过来：向量分高但关键词低。"""
        pos = [(0.95, 5.0), (0.92, 6.0)]
        neg = [(0.88, 1.0), (0.10, 2.0)]
        tv, tk, err = recommend_pair(pos, neg)
        assert err == 0, (tv, tk, err)
        assert tv > 0.88

    def test_in_domain_saved_by_either_channel(self):
        """域内样本只要有一个通道达标就该放行，不能被联合阈值误杀。"""
        pos = [(0.95, 1.0), (0.10, 99.0)]  # 一个靠向量，一个靠关键词
        neg = [(0.05, 0.5), (0.06, 0.6)]
        tv, tk, err = recommend_pair(pos, neg)
        assert err == 0, (tv, tk, err)

    def test_empty_input_is_safe(self):
        assert recommend_pair([], [(0.1, 1.0)]) == (0.0, 0.0, -1)
        assert recommend_pair([(0.9, 9.0)], []) == (0.0, 0.0, -1)

    def test_prefers_max_margin_on_tie(self):
        """错分相同时，切点应落在两组之间的空隙，而不是贴着样本点。"""
        pos = [(0.90, 50.0)]
        neg = [(0.40, 5.0)]
        tv, tk, err = recommend_pair(pos, neg)
        assert err == 0
        assert 0.40 < tv < 0.90
        assert 5.0 < tk < 50.0


class TestFmt:
    def test_empty(self):
        assert calibrate.fmt([]) == "-"

    def test_contains_key_stats(self):
        out = calibrate.fmt([0.1, 0.2, 0.3, 0.4])
        assert "min=" in out and "median=" in out and "max=" in out
