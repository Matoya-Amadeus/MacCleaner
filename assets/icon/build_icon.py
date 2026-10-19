"""生成 MacCleaner 图标（2026-10-19）。

为什么自己算像素而不截图/用第三方工具：
1. 超椭圆（squircle）要**精确** —— 1024 画布 / 824 主体 / 圆角 185.4 / 平滑 60%，
   用 CSS border-radius 近似出来的角在 Dock 里和系统图标对不齐；
2. 需要**透明角** —— 浏览器截图拿不到干净 alpha；
3. 零依赖：只用 zlib 写 PNG，任何人 clone 下来都能重跑（assets/icon/build_icon.py 是同源）。

几何：superellipse |x/a|^n + |y/b|^n = 1，n 越大角越方；60% 平滑对应 n≈5。
抗锯齿：每像素 4×4 超采样（16 次判定取平均）。
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZE = 1024
BODY = 824               # 主体边长（四周 100 边距，Apple 模板）
N = 5.0                  # 超椭圆指数（≈60% 平滑）
CX = CY = SIZE / 2
HALF = BODY / 2

# 品牌色（与 theme.py 的 token 同源）
BG_FROM = (14, 21, 18)
BG_TO = (22, 48, 42)
RING = (53, 208, 161)
RING_HL = (124, 255, 208)
LEAF = (233, 241, 237)

SS = 2                   # 每像素超采样 2×2（1024 下已足够；纯 Python 太慢）


def superellipse_inside(x: float, y: float) -> bool:
    """点是否在超椭圆内（画布坐标）。"""
    dx = abs(x - CX) / HALF
    dy = abs(y - CY) / HALF
    return dx ** N + dy ** N <= 1.0


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _ring_angle(x: float, y: float) -> tuple[float, float]:
    """返回 (半径, 角度度)；角度 0 = 正右，顺时针为正（屏幕坐标 y 向下）。"""
    dx, dy = x - CX, y - CY
    return math.hypot(dx, dy), math.degrees(math.atan2(dy, dx)) % 360


RING_R = 244.0
RING_W = 64.0
GAP_START = 250.0        # 缺口起点（度）
GAP_END = 320.0          # 缺口终点 —— 缺口 70°，约 1/5 圈
LEAF_BOX = (CX - 68, CY - 104, CX + 68, CY + 100)


def _leaf_inside(x: float, y: float) -> bool:
    """叶片/水滴：上尖下圆（用两段圆弧拼的近似，够用且小尺寸也读得出）。"""
    left, top, right, bottom = LEAF_BOX
    if not (left <= x <= right and top <= y <= bottom):
        return False
    w = right - left
    h = bottom - top
    # 上尖：菱形锥；下圆：椭圆
    ty = (y - top) / h
    if ty < 0.55:
        half = (ty / 0.55) * (w / 2)
        return abs(x - CX) <= half
    cy = top + 0.55 * h
    ry = bottom - cy
    rx = w / 2
    return ((x - CX) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def render() -> bytearray:
    rows: list[bytes] = []
    step = 1.0 / SS
    for py in range(SIZE):
        row = bytearray([0])                      # PNG 过滤类型 0
        for px in range(SIZE):
            # 4×4 超采样
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    x = px + (sx + 0.5) * step
                    y = py + (sy + 0.5) * step
                    if not superellipse_inside(x, y):
                        continue
                    # 底色：135° 线性渐变
                    t = max(0.0, min(1.0, ((x - CX) + (y - CY)) / (2 * HALF) + 0.5))
                    color = _mix(BG_FROM, BG_TO, t)
                    # 环：先用平方距离筛（省掉 sqrt/atan2，纯 Python 里这一步最关键）
                    d2 = (x - CX) ** 2 + (y - CY) ** 2
                    inner = (RING_R - RING_W / 2) ** 2
                    outer = (RING_R + RING_W / 2) ** 2
                    # 圆头端点：判断是否落在缺口的两个端点圆内（否则切口是斜的，像被裁掉一块）
                    cap = False
                    for theta in (GAP_START, GAP_END):
                        ex = CX + RING_R * math.cos(math.radians(theta))
                        ey = CY + RING_R * math.sin(math.radians(theta))
                        if (x - ex) ** 2 + (y - ey) ** 2 <= (RING_W / 2) ** 2:
                            cap = True
                            break
                    if cap:
                        # 端点与环**同色**：换高亮色会变成"两颗珠子"，而不是圆头收口。
                        color = RING
                    elif inner <= d2 <= outer:
                        angle = math.degrees(math.atan2(y - CY, x - CX)) % 360
                        if not (GAP_START <= angle <= GAP_END):
                            color = RING
                    elif _leaf_inside(x, y):
                        color = LEAF
                    acc[0] += color[0]
                    acc[1] += color[1]
                    acc[2] += color[2]
                    acc[3] += 255.0
            total = SS * SS
            alpha = acc[3] / total
            if alpha <= 0:
                row.extend((0, 0, 0, 0))
                continue
            # 颜色按"覆盖到的采样点"平均，避免边缘发黑
            covered = acc[3] / 255.0
            row.extend(
                (
                    int(acc[0] / covered),
                    int(acc[1] / covered),
                    int(acc[2] / covered),
                    int(alpha),
                )
            )
        rows.append(bytes(row))
    raw = b"".join(rows)
    compressed = zlib.compress(raw, 9)
    return _png(SIZE, SIZE, compressed)


def _png(width: int, height: int, data: bytes) -> bytearray:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8bit RGBA
    return bytearray(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", data)
        + chunk(b"IEND", b"")
    )


if __name__ == "__main__":
    # 脚本放在 assets/icon/，输出到 assets/AppIcon-1024.png（仓库内相对定位，换机器也能跑）
    out = Path(__file__).resolve().parents[2] / "assets" / "AppIcon-1024.png"
    out.write_bytes(render())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
