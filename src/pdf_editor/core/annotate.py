# -*- coding: utf-8 -*-
"""页面上手绘的笔迹与文字：只存草稿，导出时再合成进 PDF。

坐标一律用 0~1 的归一化值（相对页面宽高），这样缩放、换 DPI 都不会错位。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import pymupdf

# 常用中文字体：显示名 → Windows 字体文件（找不到就退回内置宋体）
FONT_FILES = {
    "微软雅黑": "msyh.ttc",
    "宋体": "simsun.ttc",
    "黑体": "simhei.ttf",
    "楷体": "simkai.ttf",
    "仿宋": "simfang.ttf",
}

FONT_NAMES = list(FONT_FILES)

# 笔画宽度以「千分之一页宽」为单位存，导出时按实际页宽换算
WIDTH_BASE = 1000.0


def font_path(name: str) -> str | None:
    fname = FONT_FILES.get(name)
    if not fname:
        return None
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", fname)
    return path if os.path.exists(path) else None


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = (int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0.0, 0.0, 0.0)
    return (r, g, b)


@dataclass
class InkStroke:
    """一条自由笔迹。points 为归一化坐标点列。"""

    points: list[tuple[float, float]] = field(default_factory=list)
    color: str = "#E5484D"
    width: float = 3.0          # 千分之一页宽

    def copy(self) -> InkStroke:
        return InkStroke(list(self.points), self.color, self.width)


@dataclass
class TextMark:
    """一段贴上去的文字，x/y 为左上角锚点（归一化）。"""

    x: float = 0.1
    y: float = 0.1
    text: str = ""
    color: str = "#1A2030"
    font: str = "微软雅黑"
    size: float = 0.045         # 字高占页高的比例

    def copy(self) -> TextMark:
        return TextMark(self.x, self.y, self.text, self.color, self.font, self.size)


def draw_strokes(page: pymupdf.Page, strokes: list[InkStroke]) -> None:
    """把笔迹画到页面上（矢量，不损失清晰度）。"""
    if not strokes:
        return
    w = page.rect.width
    for s in strokes:
        if len(s.points) < 2:
            continue
        pts = [pymupdf.Point(p[0] * page.rect.width, p[1] * page.rect.height)
               for p in s.points]
        shape = page.new_shape()
        shape.draw_polyline(pts)
        shape.finish(color=hex_to_rgb(s.color), width=max(0.3, s.width * w / WIDTH_BASE),
                     lineCap=1, lineJoin=1, closePath=False)
        shape.commit(overlay=True)


def draw_texts(page: pymupdf.Page, texts: list[TextMark]) -> None:
    """把文字贴到页面上；优先用系统字体，缺失时退回内置宋体。"""
    if not texts:
        return
    for t in texts:
        if not t.text.strip():
            continue
        size = max(4.0, t.size * page.rect.height)
        pt = pymupdf.Point(t.x * page.rect.width, t.y * page.rect.height + size)
        path = font_path(t.font)
        fontname = "china-s"
        if path:
            try:
                page.insert_font(fontname="CNU", fontfile=path)
                fontname = "CNU"
            except Exception:  # noqa: BLE001
                fontname = "china-s"
        try:
            page.insert_text(pt, t.text, fontname=fontname, fontsize=size,
                             color=hex_to_rgb(t.color), overlay=True)
        except Exception:  # noqa: BLE001
            page.insert_text(pt, t.text, fontname="china-s", fontsize=size,
                             color=hex_to_rgb(t.color), overlay=True)
