"""核心对齐算法。

约定：
- 文本按 Unicode 码点处理（Python str 即码点序列）。
- 编辑距离：插入、删除、替换各计 1（Levenshtein）。
- 标签跨度为码点左闭右开区间 [start, end)。

关键结论：标签跨度 [a, b) 能在某个最优对齐中完整连续地保留并落到
修订文 [p, p+L)（L = b-a），当且仅当：
  1) t[p:p+L] == s[a:b]（逐字符相同）
  2) d1[a][p] + d2[b][p+L] == D
其中 d1[i][j] 是 s[:i] -> t[:j] 的最短编辑距离，d2[i][j] 是
s[i:] -> t[j:] 的最短编辑距离，D = d1[m][n] 是全局最短编辑距离。
充分性：前缀最优对齐 + 跨度逐字匹配 + 后缀最优对齐即构成一个最优对齐；
必要性：任一保留该跨度的最优对齐在这三段上的代价分别不小于对应下界。
"""

from __future__ import annotations

from itertools import combinations
from typing import Sequence


def edit_distance(s: str, t: str) -> int:
    """普通 Levenshtein 距离（插/删/换各计 1）。"""
    m, n = len(s), len(t)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        si = s[i - 1]
        for j in range(1, n + 1):
            cost = 0 if si == t[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def compute_tables(s: str, t: str):
    """返回 (d1, d2, D)。

    d1[i][j] = ed(s[:i], t[:j])；d2[i][j] = ed(s[i:], t[j:])；D = d1[m][n]。
    """
    m, n = len(s), len(t)
    d1 = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        d1[i][0] = i
    for j in range(1, n + 1):
        d1[0][j] = j
    for i in range(1, m + 1):
        si = s[i - 1]
        row, prow = d1[i], d1[i - 1]
        for j in range(1, n + 1):
            cost = 0 if si == t[j - 1] else 1
            row[j] = min(prow[j] + 1, row[j - 1] + 1, prow[j - 1] + cost)

    d2 = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        d2[i][n] = m - i          # 删光 s[i:]
    for j in range(n + 1):
        d2[m][j] = n - j          # 插入 t[j:]
    for i in range(m - 1, -1, -1):
        si = s[i]
        row, nrow = d2[i], d2[i + 1]
        for j in range(n - 1, -1, -1):
            cost = 0 if si == t[j] else 1
            row[j] = min(nrow[j] + 1, row[j + 1] + 1, nrow[j + 1] + cost)
    return d1, d2, d1[m][n]


def compute_counts(s: str, t: str, d1, d2):
    """最优对齐计数表。

    c1[i][j] = 从 (0,0) 到 (i,j) 的最优路径条数；
    c2[i][j] = 从 (i,j) 到 (m,n) 的最优路径条数。
    c1[m][n] == c2[0][0] == 最优对齐总数（Python 大整数，不怕爆炸）。
    """
    m, n = len(s), len(t)
    c1 = [[0] * (n + 1) for _ in range(m + 1)]
    c1[0][0] = 1
    for i in range(m + 1):
        for j in range(n + 1):
            if i == 0 and j == 0:
                continue
            total = 0
            if i > 0 and d1[i][j] == d1[i - 1][j] + 1:
                total += c1[i - 1][j]
            if j > 0 and d1[i][j] == d1[i][j - 1] + 1:
                total += c1[i][j - 1]
            if i > 0 and j > 0:
                cost = 0 if s[i - 1] == t[j - 1] else 1
                if d1[i][j] == d1[i - 1][j - 1] + cost:
                    total += c1[i - 1][j - 1]
            c1[i][j] = total

    c2 = [[0] * (n + 1) for _ in range(m + 1)]
    c2[m][n] = 1
    for i in range(m, -1, -1):
        for j in range(n, -1, -1):
            if i == m and j == n:
                continue
            total = 0
            if i < m and d2[i][j] == d2[i + 1][j] + 1:
                total += c2[i + 1][j]
            if j < n and d2[i][j] == d2[i][j + 1] + 1:
                total += c2[i][j + 1]
            if i < m and j < n:
                cost = 0 if s[i] == t[j] else 1
                if d2[i][j] == d2[i + 1][j + 1] + cost:
                    total += c2[i + 1][j + 1]
            c2[i][j] = total
    return c1, c2


def possible_positions(s: str, t: str, a: int, b: int,
                       d1, d2, D: int) -> list[int]:
    """标签 [a,b) 在所有最优对齐中完整连续保留时，在 t 中的全部落点起点。"""
    L = b - a
    n = len(t)
    seg = s[a:b]
    res = []
    for p in range(0, n - L + 1):
        if t[p:p + L] == seg and d1[a][p] + d2[b][p + L] == D:
            res.append(p)
    return res


def analyze_labels(s: str, t: str, labels: Sequence[dict]) -> dict:
    """对每个标签计算状态：

    - auto:       所有最优对齐都保留该跨度且落点唯一 -> 自动迁移
    - choice:     有落点但不满足 auto（多个落点，或唯一落点却并非所有
                  最优对齐都保留）-> 需要用户选择或丢弃
    - impossible: 任何最优对齐都无法完整连续保留 -> 只能丢弃

    判定“所有最优对齐都保留”用计数：保留该跨度的最优对齐数
    sum_p c1[a][p] * c2[b][p+L] 等于最优对齐总数 c1[m][n]。
    """
    d1, d2, D = compute_tables(s, t)
    c1, c2 = compute_counts(s, t, d1, d2)
    total_alignments = c1[len(s)][len(t)]
    out = []
    for lab in labels:
        a, b = lab["start"], lab["end"]
        L = b - a
        poss = possible_positions(s, t, a, b, d1, d2, D)
        kept = sum(c1[a][p] * c2[b][p + L] for p in poss)
        preserved_in_all = bool(poss) and kept == total_alignments
        if not poss:
            status = "impossible"
        elif len(poss) == 1 and preserved_in_all:
            status = "auto"
        else:
            status = "choice"
        out.append({
            "id": lab["id"],
            "start": a,
            "end": b,
            "text": s[a:b],
            "status": status,
            "possible": poss,
            "preserved_in_all": preserved_in_all,
        })
    return {"distance": D, "labels": out}


def _segments_cost(s: str, t: str, kept: Sequence[tuple[int, int, int]]) -> int:
    """固定若干跨度映射 (a,b)->p 后，剩余各段最短编辑代价之和。"""
    total = 0
    prev_a, prev_p = 0, 0
    for a, b, p in kept:
        total += edit_distance(s[prev_a:a], t[prev_p:p])
        prev_a, prev_p = b, p + (b - a)
    total += edit_distance(s[prev_a:], t[prev_p:])
    return total


def _order_violations(kept: Sequence[tuple[int, int, int]]) -> list[int]:
    """kept 按源区间升序；目标区间也必须同序且不重叠，否则返回冲突下标。"""
    bad = set()
    for i in range(len(kept) - 1):
        a1, b1, p1 = kept[i]
        _, _, p2 = kept[i + 1]
        if p1 + (b1 - a1) > p2:
            bad.add(i)
            bad.add(i + 1)
    return sorted(bad)


def _consistent(s: str, t: str, kept: Sequence[tuple[int, int, int]], D: int) -> bool:
    if _order_violations(kept):
        return False
    return _segments_cost(s, t, kept) == D


def check_joint(s: str, t: str, kept: Sequence[tuple[int, int, int]],
                D: int) -> tuple[bool, list[int]]:
    """检查整份选择是否能被同一个最优对齐支持。

    kept: [(a, b, p), ...] 按 a 升序。返回 (是否一致, 冲突标签在 kept 中的下标)。
    冲突定位：先查目标区间次序冲突；再查代价冲突，取一个极小的不一致子集。
    """
    kept = sorted(kept, key=lambda x: x[0])
    bad = _order_violations(kept)
    if bad:
        return False, bad
    if _segments_cost(s, t, kept) == D:
        return True, []
    # 代价冲突：寻找极小的不一致子集（单标签必然一致，故从 2 开始）
    for size in range(2, len(kept) + 1):
        for combo in combinations(range(len(kept)), size):
            sub = [kept[i] for i in combo]
            if not _consistent(s, t, sub, D):
                return False, sorted(combo)
    return False, list(range(len(kept)))  # 理论上不可达，兜底
