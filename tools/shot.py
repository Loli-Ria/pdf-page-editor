# -*- coding: utf-8 -*-
"""离屏截图：不碰桌面，把窗口直接 grab 成 PNG，用来检查界面。

用法：python tools/shot.py [宽] [高] [输出名]
"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import pymupdf
from PIL import Image, ImageDraw
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pdf_editor.app import RESOURCES
from pdf_editor.core import annotate
from pdf_editor.ui import theme
from pdf_editor.ui.main_window import MainWindow

OUT = os.path.join(ROOT, "build", "shots")   # 临时截图，不进仓库


def make_pdf(path: str, n: int, tag: str) -> None:
    doc = pymupdf.open()
    for i in range(n):
        page = doc.new_page(width=595, height=842)
        page.draw_rect(pymupdf.Rect(40, 40, 555, 802), color=(0.85, 0.2, 0.2), width=2)
        page.insert_text((70, 120), f"{tag} - Page {i + 1}", fontsize=26)
        page.insert_text((70, 170), "PDF 页数编辑器 / 多文件导入验证", fontsize=14)
    doc.save(path)
    doc.close()


def make_img(path: str, size: tuple[int, int], color, tag: str) -> None:
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    d.rectangle([16, 16, size[0] - 16, size[1] - 16], outline=(30, 40, 60), width=6)
    d.text((40, 40), tag, fill=(20, 30, 50))
    im.save(path)


def main() -> None:
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1400
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 900
    name = sys.argv[3] if len(sys.argv) > 3 else "split"

    tmp = tempfile.mkdtemp(prefix="pdfshot_")
    p1 = os.path.join(tmp, "扫描全能王 2026-11-18.pdf")
    p2 = os.path.join(tmp, "颜荡桥处置补充材料.pdf")
    make_pdf(p1, 23, "SCAN")
    make_pdf(p2, 6, "SUPP")
    i1 = os.path.join(tmp, "现场照片_东侧.jpg")
    i2 = os.path.join(tmp, "现场照片_西侧.jpg")
    make_img(i1, (1200, 1600), (200, 220, 255), "PHOTO EAST")
    make_img(i2, (1600, 1200), (255, 232, 205), "PHOTO WEST")

    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv[:1])
    theme.set_resource_dir(RESOURCES)
    app.setStyleSheet(theme.app_qss())

    win = MainWindow()
    win.resize(w, h)
    win.show()
    if "wide" in name:
        # 预览栏拉到最大，检查是否会和缩略图区打架
        win.split_page.split.setSizes([9999, 1])
    elif "note" in name:
        # 批注 + 附加处理全部展开，检查排版
        sp = win.split_page
        sp.add_sources([p1, p2, i1, i2])
        sp.notes[(0, 0)] = [
            annotate.InkStroke([(0.22, 0.30), (0.40, 0.33), (0.58, 0.28),
                                (0.66, 0.40), (0.52, 0.46)],
                               "#E5484D", 8.0),
            annotate.TextMark(0.22, 0.52, "这里要改一下", "#4F6BFF", "黑体", 0.05),
        ]
        sp.chk_num.setChecked(True)
        sp.chk_wm.setChecked(True)
        sp.wm_edit.setText("内部资料")
        sp.tile_box.setCurrentIndex(1)
        sp.chk_zip.setChecked(True)
        QTimer.singleShot(1200, sp._refresh_preview)
    elif "many" in name:
        # 压测：一次导入 14 个文件，看标签区是否还老实待在两行以内
        extra = []
        for k in range(12):
            path = os.path.join(tmp, f"材料{k + 1:02d}_扫描件.pdf")
            make_pdf(path, 2, f"M{k + 1:02d}")
            extra.append(path)
        win.split_page.add_sources(extra + [i1, i2])
    else:
        win.split_page.add_sources([p1, p2, i1, i2])

    def shoot() -> None:
        path = os.path.join(OUT, f"{name}.png")
        win.grab().save(path)
        print("saved:", path)
        win.close()
        app.quit()

    QTimer.singleShot(2600, shoot)
    app.exec()


if __name__ == "__main__":
    main()
