"""Squarified treemap 布局（纯计算，便于单测）。

为什么自己做而不是前端算：布局是**确定性的数学**，放在 Python 里能直接被用例覆盖
（面积是否按比例、矩形是否越界/重叠），前端只负责画。

算法：Bruls/Huizing/van Wijk 的 squarified treemap —— 逐行填充，每步选让"最差长宽比"
最小的那个切法。相比 slice-and-dice，它不会产生又细又长的条，面积小的项也看得见。
"""
from __future__ import annotations

from typing import Iterable, Sequence


def _worst_ratio(row: Sequence[float], side: float) -> float:
    if not row or side <= 0:
        return float("inf")
    total = sum(row)
    if total <= 0:
        return float("inf")
    biggest, smallest = max(row), min(row)
    if smallest <= 0:
        return float("inf")
    return max((side * side * biggest) / (total * total), (total * total) / (side * side * smallest))


def squarify(
    values: Iterable[float], width: float, height: float
) -> list[tuple[float, float, float, float]]:
    """把一组数值铺满 `width × height`，返回同顺序的 `(x, y, w, h)`。

    数值会被缩放到面积总和 = 宽×高；<=0 的项返回零面积矩形（保持下标对齐）。
    """
    raw = [max(0.0, float(value)) for value in values]
    total = sum(raw)
    if total <= 0 or width <= 0 or height <= 0:
        return [(0.0, 0.0, 0.0, 0.0) for _ in raw]

    scale = (width * height) / total
    areas = [value * scale for value in raw]
    # 大块先排，观感更稳；最后按原下标回填。
    order = sorted(range(len(areas)), key=lambda index: -areas[index])
    rects: list[tuple[float, float, float, float]] = [(0.0, 0.0, 0.0, 0.0)] * len(areas)

    x, y, free_w, free_h = 0.0, 0.0, float(width), float(height)
    row: list[int] = []

    def flush() -> None:
        nonlocal x, y, free_w, free_h
        if not row:
            return
        row_area = sum(areas[index] for index in row)
        if row_area <= 0:
            row.clear()
            return
        if free_w >= free_h:
            # 竖条：宽度按面积占比，行内从上往下切
            strip_w = row_area / free_h if free_h else 0.0
            offset = 0.0
            for index in row:
                piece_h = areas[index] / strip_w if strip_w else 0.0
                rects[index] = (x, y + offset, strip_w, piece_h)
                offset += piece_h
            x += strip_w
            free_w -= strip_w
        else:
            strip_h = row_area / free_w if free_w else 0.0
            offset = 0.0
            for index in row:
                piece_w = areas[index] / strip_h if strip_h else 0.0
                rects[index] = (x + offset, y, piece_w, strip_h)
                offset += piece_w
            y += strip_h
            free_h -= strip_h
        row.clear()

    for index in order:
        if areas[index] <= 0:
            continue
        side = min(free_w, free_h)
        candidate = row + [index]
        if not row or _worst_ratio([areas[i] for i in candidate], side) <= _worst_ratio(
            [areas[i] for i in row], side
        ):
            row = candidate
        else:
            flush()
            row = [index]
    flush()
    return rects
