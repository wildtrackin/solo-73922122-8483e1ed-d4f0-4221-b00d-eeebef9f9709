"""输入校验与规范化。

约束（与需求一致）：
- 原文、修订文各至多 120 个 Unicode 码点（Python str 长度即码点数）。
- 标签至多 10 个；每个标签非空（start < end）、落在原文范围内、互不重叠
  （左闭右开区间，故 end == 下一个 start 是允许的）。
- 标签 id 可缺省，自动补 L1..Ln；若提供必须唯一。
"""

from __future__ import annotations

MAX_TEXT_LEN = 120
MAX_LABELS = 10


class ValidationError(ValueError):
    """输入校验失败，message 面向用户。"""


def validate_text(value, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field} 必须是字符串")
    if len(value) > MAX_TEXT_LEN:
        raise ValidationError(
            f"{field} 超长：{len(value)} 个码点，上限 {MAX_TEXT_LEN}")
    return value


def normalize_labels(raw, original: str) -> list[dict]:
    """把用户上传的标签 JSON 规范化为 [{id, start, end}]（按 start 升序）。"""
    if isinstance(raw, dict) and "labels" in raw:
        raw = raw["labels"]
    if not isinstance(raw, list):
        raise ValidationError("标签 JSON 必须是数组，或形如 {\"labels\": [...]} 的对象")
    if len(raw) > MAX_LABELS:
        raise ValidationError(f"标签数量 {len(raw)} 超过上限 {MAX_LABELS}")

    n = len(original)
    out = []
    seen_ids = set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise ValidationError(f"第 {i} 个标签不是对象")
        lid = item.get("id")
        if lid is None:
            lid = f"L{i}"
        if not isinstance(lid, str) or not lid.strip():
            raise ValidationError(f"第 {i} 个标签的 id 必须是非空字符串")
        lid = lid.strip()
        if lid in seen_ids:
            raise ValidationError(f"标签 id 重复：{lid!r}")
        seen_ids.add(lid)

        start, end = item.get("start"), item.get("end")
        for name, v in (("start", start), ("end", end)):
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValidationError(f"标签 {lid!r} 的 {name} 必须是整数")
        if not (0 <= start < end <= n):
            raise ValidationError(
                f"标签 {lid!r} 区间 [{start}, {end}) 非法：须满足 "
                f"0 <= start < end <= 原文长度 {n}（标签不能为空）")
        out.append({"id": lid, "start": start, "end": end})

    out.sort(key=lambda x: (x["start"], x["end"]))
    for prev, cur in zip(out, out[1:]):
        if cur["start"] < prev["end"]:
            raise ValidationError(
                f"标签 {prev['id']!r} 与 {cur['id']!r} 区间重叠")
    return out


def normalize_selections(raw, labels: list[dict]) -> dict:
    """规范化选择表：{label_id: {"choice": "position"|"discard", "position": int?}}"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValidationError("selections 必须是对象：{标签id: 选择}")
    known = {lab["id"] for lab in labels}
    out = {}
    for lid, sel in raw.items():
        if lid not in known:
            raise ValidationError(f"选择指向未知标签：{lid!r}")
        if not isinstance(sel, dict):
            raise ValidationError(f"标签 {lid!r} 的选择必须是对象")
        choice = sel.get("choice")
        if choice == "discard":
            out[lid] = {"choice": "discard"}
        elif choice == "position":
            pos = sel.get("position")
            if not isinstance(pos, int) or isinstance(pos, bool):
                raise ValidationError(f"标签 {lid!r} 的 position 必须是整数")
            out[lid] = {"choice": "position", "position": pos}
        else:
            raise ValidationError(
                f"标签 {lid!r} 的 choice 必须是 \"position\" 或 \"discard\"")
    return out
