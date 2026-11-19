# -*- coding: utf-8 -*-
"""生成界面用到的全部图片资源：

- icon.png / icon.ico   应用图标
- check_on.png / check_off.png 复选框勾选图标（各带 @2x 版本）

运行：python tools/make_assets.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "src", "pdf_editor", "resources")

S = 512
C1 = (79, 107, 255)
C2 = (128, 92, 255)
SS = 8          # 超采样倍数，画完再缩小以获得平滑边缘


def gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        d.line([(0, y), (size, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(C1, C2)))
    return img


def build_icon(size: int = S) -> Image.Image:
    base = gradient(size)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(size * 0.235), fill=255)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(base, (0, 0), mask)
    d = ImageDraw.Draw(icon)

    # 纸张
    w, h = int(size * 0.40), int(size * 0.50)
    x0, y0 = (size - w) // 2, int(size * 0.245)
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h],
                        radius=int(size * 0.035), fill=(255, 255, 255, 245))

    # 折角
    fold = int(size * 0.11)
    d.polygon([(x0 + w - fold, y0), (x0 + w, y0 + fold), (x0 + w - fold, y0 + fold)],
              fill=(214, 222, 255, 255))

    # 中间拆分虚线
    y = y0 + int(h * 0.52)
    dash, gap = int(size * 0.035), int(size * 0.022)
    x = x0 + int(w * 0.14)
    x_end = x0 + w - int(w * 0.14)
    while x < x_end:
        d.rounded_rectangle([x, y - int(size * 0.008), min(x + dash, x_end),
                             y + int(size * 0.008)],
                            radius=int(size * 0.008), fill=C1 + (255,))
        x += dash + gap

    # 上方两条文字线
    for i in range(2):
        yy = y0 + int(h * (0.24 + i * 0.12))
        d.rounded_rectangle([x0 + int(w * 0.14), yy, x0 + int(w * 0.72),
                             yy + int(size * 0.014)],
                            radius=int(size * 0.007), fill=(196, 206, 236, 255))
    return icon


def build_check(size: int, on: bool) -> Image.Image:
    """size 是输出边长；内部按 SS 倍超采样绘制。"""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(n * 0.10)
    radius = int(n * 0.26)
    box = [pad, pad, n - pad, n - pad]
    if on:
        d.rounded_rectangle(box, radius=radius, fill=C1 + (255,))
        # 白色对勾
        w = max(int(n * 0.11), 2)
        p1 = (int(n * 0.28), int(n * 0.52))
        p2 = (int(n * 0.44), int(n * 0.68))
        p3 = (int(n * 0.73), int(n * 0.35))
        d.line([p1, p2], fill=(255, 255, 255, 255), width=w)
        d.line([p2, p3], fill=(255, 255, 255, 255), width=w)
        for p in (p1, p2, p3):
            d.ellipse([p[0] - w // 2, p[1] - w // 2, p[0] + w // 2, p[1] + w // 2],
                      fill=(255, 255, 255, 255))
    else:
        d.rounded_rectangle(box, radius=radius, fill=(255, 255, 255, 255),
                            outline=(207, 214, 228, 255),
                            width=max(int(n * 0.085), 2))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    icon = build_icon(S)
    png = os.path.join(OUT, "icon.png")
    icon.save(png)
    ico = os.path.join(OUT, "icon.ico")
    icon.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
    print("saved:", png, os.path.getsize(png), "bytes")
    print("saved:", ico, os.path.getsize(ico), "bytes")

    for base in (32, 64):
        for on in (True, False):
            name = "check_on" if on else "check_off"
            suffix = "" if base == 32 else "@2x"
            path = os.path.join(OUT, f"{name}{suffix}.png")
            build_check(base, on).save(path)
            print("saved:", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    main()
