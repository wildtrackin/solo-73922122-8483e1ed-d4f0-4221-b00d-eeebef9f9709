"""暴力枚举对照测试：

对小字符串枚举全部最优对齐，逐跨度验证：
1. possible_positions 给出的落点集合 == 暴力枚举得到的集合；
2. check_joint 的一致性判定 == 暴力枚举“存在同一最优对齐支持全部映射”。
"""

import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.alignment import (analyze_labels, check_joint, compute_tables,
                           edit_distance, possible_positions)


def brute_alignments(s: str, t: str):
    """返回所有最优对齐的“匹配对集合”列表。匹配对 (i,j) 表示 s[i] 与 t[j]
    在最优对齐中逐字对应（替换不算匹配）。"""
    m, n = len(s), len(t)
    D = edit_distance(s, t)
    found = set()

    def rec(i, j, cost, pairs):
        if cost > D:
            return
        if i == m and j == n:
            if cost == D:
                found.add(tuple(pairs))
            return
        if i < m and j < n:
            if s[i] == t[j]:
                rec(i + 1, j + 1, cost, pairs + ((i, j),))
            else:
                rec(i + 1, j + 1, cost + 1, pairs)   # 替换：不算匹配
        if i < m:
            rec(i + 1, j, cost + 1, pairs)           # 删除 s[i]
        if j < n:
            rec(i, j + 1, cost + 1, pairs)           # 插入 t[j]

    rec(0, 0, 0, ())
    return [set(p) for p in found]


def brute_possible(s: str, t: str, a: int, b: int, aligns) -> list[int]:
    L = b - a
    out = set()
    for pairs in aligns:
        d = dict(pairs)
        if all(i in d for i in range(a, b)):
            ps = [d[i] for i in range(a, b)]
            if ps == list(range(ps[0], ps[0] + L)):
                out.add(ps[0])
    return sorted(out)


def brute_preserved_in_all(s: str, t: str, a: int, b: int, aligns) -> bool:
    """每个最优对齐都完整连续保留该跨度（落点可不同）。"""
    L = b - a
    for pairs in aligns:
        d = dict(pairs)
        if not all(i in d for i in range(a, b)):
            return False
        ps = [d[i] for i in range(a, b)]
        if ps != list(range(ps[0], ps[0] + L)):
            return False
    return True


def brute_joint(s: str, t: str, kept, aligns) -> bool:
    for pairs in aligns:
        d = dict(pairs)
        ok = True
        for a, b, p in kept:
            L = b - a
            if not all(d.get(i) == p + (i - a) for i in range(a, b)):
                ok = False
                break
        if ok:
            return True
    return False


def all_strings(alphabet, max_len):
    out = [""]
    for L in range(1, max_len + 1):
        out += ["".join(c) for c in product(alphabet, repeat=L)]
    return out


def test_possible_positions_match_bruteforce():
    strs = all_strings("ab", 4)
    for s in strs:
        for t in strs:
            aligns = brute_alignments(s, t)
            d1, d2, D = compute_tables(s, t)
            for a in range(len(s)):
                for b in range(a + 1, len(s) + 1):
                    got = possible_positions(s, t, a, b, d1, d2, D)
                    want = brute_possible(s, t, a, b, aligns)
                    assert got == want, (s, t, a, b, got, want)


def test_preserved_in_all_matches_bruteforce():
    strs = all_strings("ab", 4)
    for s in strs:
        for t in strs:
            aligns = brute_alignments(s, t)
            labels = [{"id": f"{a}-{b}", "start": a, "end": b}
                      for a in range(len(s)) for b in range(a + 1, len(s) + 1)]
            if not labels:
                continue
            res = analyze_labels(s, t, labels)
            for info in res["labels"]:
                want = brute_preserved_in_all(
                    s, t, info["start"], info["end"], aligns)
                assert info["preserved_in_all"] == want, (s, t, info, want)
                # auto 当且仅当：落点唯一且所有最优对齐都保留
                want_auto = want and len(info["possible"]) == 1
                assert (info["status"] == "auto") == want_auto, (s, t, info)
                if not info["possible"]:
                    assert info["status"] == "impossible"


def test_joint_check_matches_bruteforce():
    strs = all_strings("ab", 4)
    for s in strs:
        for t in strs:
            aligns = brute_alignments(s, t)
            d1, d2, D = compute_tables(s, t)
            spans = [(a, b) for a in range(len(s))
                     for b in range(a + 1, len(s) + 1)]
            # 单映射 + 双映射组合
            singles = []
            for a, b in spans:
                for p in possible_positions(s, t, a, b, d1, d2, D):
                    singles.append((a, b, p))
            cases = [[m] for m in singles]
            for i, m1 in enumerate(singles):
                for m2 in singles[i + 1:]:
                    if m1[1] <= m2[0]:          # 源区间不重叠才有意义
                        cases.append([m1, m2])
            for kept in cases:
                ok, _bad = check_joint(s, t, kept, D)
                want = brute_joint(s, t, kept, aligns)
                assert ok == want, (s, t, kept, ok, want)


def test_random_triples_longer():
    """稍长字符串上再抽查落点集合（含三字符字母表与重复结构）。"""
    import random
    rng = random.Random(20261116)
    for _ in range(150):
        s = "".join(rng.choice("aab") for _ in range(rng.randint(0, 7)))
        t = "".join(rng.choice("aab") for _ in range(rng.randint(0, 7)))
        aligns = brute_alignments(s, t)
        d1, d2, D = compute_tables(s, t)
        for a in range(len(s)):
            for b in range(a + 1, len(s) + 1):
                got = possible_positions(s, t, a, b, d1, d2, D)
                want = brute_possible(s, t, a, b, aligns)
                assert got == want, (s, t, a, b, got, want)
