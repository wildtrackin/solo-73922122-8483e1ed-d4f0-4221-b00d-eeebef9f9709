"""核心对齐算法的单元测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alignment import (analyze_labels, check_joint, compute_tables,
                           edit_distance, possible_positions)


def poss(s, t, a, b):
    d1, d2, D = compute_tables(s, t)
    return possible_positions(s, t, a, b, d1, d2, D)


class TestEditDistance:
    def test_basic(self):
        assert edit_distance("", "") == 0
        assert edit_distance("abc", "abc") == 0
        assert edit_distance("abc", "abd") == 1      # 替换
        assert edit_distance("abc", "abcd") == 1     # 插入
        assert edit_distance("abcd", "abc") == 1     # 删除
        assert edit_distance("kitten", "sitting") == 3

    def test_astral_codepoints(self):
        # emoji 是单码点：替换它计 1，而不是 2
        assert edit_distance("a😀b", "a😃b") == 1
        assert edit_distance("😀😀", "😀") == 1


class TestPossiblePositions:
    def test_identical_texts(self):
        assert poss("abcdef", "abcdef", 0, 3) == [0]
        assert poss("abcdef", "abcdef", 3, 6) == [3]

    def test_auto_after_append(self):
        assert poss("语料工程师修订OCR文本", "语料工程师修订OCR文本内容", 0, 5) == [0]
        assert poss("语料工程师修订OCR文本", "语料工程师修订OCR文本内容", 7, 10) == [7]

    def test_replacement_inside_label_impossible(self):
        # “行”被替换，跨度“银行”无法完整保留
        assert poss("中国人民银行", "中国人民银号", 4, 6) == []

    def test_replacement_outside_label_kept(self):
        assert poss("中国人民银行", "中国人民银号", 0, 4) == [0]

    def test_repeated_text_ambiguous(self):
        # abcabcabc -> abcabc：中间那段 abc 可能来自第 1 或第 2 个重复单元
        assert poss("abcabcabc", "abcabc", 3, 6) == [0, 3]

    def test_repeated_text_exact_sets(self):
        d1, d2, D = compute_tables("abcabcabc", "abcabc")
        assert D == 3
        # 首块只能来自“保留首块”的对齐 -> 唯一落点 0
        assert possible_positions("abcabcabc", "abcabc", 0, 3, d1, d2, D) == [0]
        # 中间块可来自第 1 或第 2 个保留块 -> 两个落点
        assert possible_positions("abcabcabc", "abcabc", 3, 6, d1, d2, D) == [0, 3]
        # 尾块对称地唯一 -> 3
        assert possible_positions("abcabcabc", "abcabc", 6, 9, d1, d2, D) == [3]

    def test_deletion_inside_label_impossible(self):
        assert poss("abcd", "abd", 0, 4) == []       # 整段含被删字符
        assert poss("abcd", "abd", 0, 2) == [0]      # 前段保留
        assert poss("abcd", "abd", 3, 4) == [2]      # 后段保留并前移

    def test_label_longer_than_text(self):
        assert poss("abcdef", "ab", 0, 4) == []


class TestAnalyzeLabels:
    def test_statuses(self):
        labels = [
            {"id": "a", "start": 0, "end": 3},
            {"id": "b", "start": 3, "end": 6},
        ]
        res = analyze_labels("abcabcabc", "abcabc", labels)
        assert res["distance"] == 3
        st = {l["id"]: l["status"] for l in res["labels"]}
        # a 落点唯一为 [0]，但并非所有最优对齐都保留它（有的对齐删的是首块），
        # 故不是 auto，而是只有一个选项的 choice；b 同理有两个落点。
        assert st == {"a": "choice", "b": "choice"}
        info = {l["id"]: l for l in res["labels"]}
        assert info["a"]["possible"] == [0] and not info["a"]["preserved_in_all"]
        assert info["b"]["possible"] == [0, 3]

    def test_auto_and_impossible(self):
        labels = [
            {"id": "keep", "start": 0, "end": 4},
            {"id": "lost", "start": 4, "end": 6},
        ]
        res = analyze_labels("中国人民银行", "中国人民银号", labels)
        st = {l["id"]: l["status"] for l in res["labels"]}
        assert st == {"keep": "auto", "lost": "impossible"}


class TestCheckJoint:
    def test_empty_selection_consistent(self):
        ok, bad = check_joint("abc", "axc", [], 1)
        assert ok and bad == []

    def test_consistent_pair(self):
        # abXcd -> abYcd，两段各自迁移，联合一致
        ok, bad = check_joint("abXcd", "abYcd", [(0, 2, 0), (3, 5, 3)], 1)
        assert ok and bad == []

    def test_order_conflict_same_target(self):
        # abab -> ab：两个 ab 都只能落在 [0,2)，互相冲突
        ok, bad = check_joint("abab", "ab", [(0, 2, 0), (2, 4, 0)], 2)
        assert not ok
        assert bad == [0, 1]

    def test_order_conflict_inversion(self):
        # ab -> ba：a 只能去 1，b 只能去 0，目标次序颠倒
        ok, bad = check_joint("ab", "ba", [(0, 1, 1), (1, 2, 0)], 2)
        assert not ok
        assert bad == [0, 1]

    def test_partial_keep_consistent(self):
        # abab -> ab：只保留第二个 ab -> [0,2)，一致
        ok, _ = check_joint("abab", "ab", [(2, 4, 0)], 2)
        assert ok

    def test_conflict_subset_reported(self):
        # 三个标签，其中两个冲突：应报告冲突的那对
        s, t = "abab", "ab"
        kept = [(0, 2, 0), (2, 4, 0)]
        ok, bad = check_joint(s, t, kept, 2)
        assert not ok and bad == [0, 1]

    def test_cost_conflict_without_order_violation(self):
        # 构造：落点次序合法，但拼不出一个最优对齐
        # s="aab", t="ab", D=1
        # 标签1 [0,1)"a" -> 0（删第二个 a）
        # 标签2 [2,3)"b" -> 1
        # 单独看：标签2 也可以 -> 1（d1[2][1]=1）。两者联合：
        # 段代价 = d1[0][0] + ed("a", "") + d2[3][2] = 0+1+0 = 1 == D，一致。
        ok, _ = check_joint("aab", "ab", [(0, 1, 0), (2, 3, 1)], 1)
        assert ok
        # 而 标签1' [1,2)"a" -> 0 与 标签2 [2,3)"b" -> 1 也一致（删第一个 a）
        ok2, _ = check_joint("aab", "ab", [(1, 2, 0), (2, 3, 1)], 1)
        assert ok2


class TestAstralLabels:
    def test_emoji_label_positions(self):
        s, t = "😀x😀", "😀😀"
        # 删 x：标签 [0,1) -> 0；[2,3) -> 1
        assert poss(s, t, 0, 1) == [0]
        assert poss(s, t, 2, 3) == [1]
