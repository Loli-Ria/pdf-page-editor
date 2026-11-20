# -*- coding: utf-8 -*-
"""新功能自测：导出图片 / 页码水印 / 压缩 / 拼接 / 手绘批注。

直接运行：python tests/test_features.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pymupdf  # noqa: E402
from PIL import Image  # noqa: E402

from pdf_editor.core import annotate  # noqa: E402
from pdf_editor.core import engine as E  # noqa: E402

TMP = tempfile.mkdtemp(prefix="pdftest_")
passed = 0
failed: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name} {extra}")


def make_pdf(path: str, pages: int, text: str) -> None:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"{text} - Page {i + 1}", fontsize=20)
    doc.save(path)
    doc.close()


def main() -> int:
    pdf_a = os.path.join(TMP, "a.pdf")
    pdf_b = os.path.join(TMP, "b.pdf")
    img = os.path.join(TMP, "photo.jpg")
    make_pdf(pdf_a, 5, "SCAN A")
    make_pdf(pdf_b, 3, "SCAN B")
    Image.new("RGB", (800, 1200), (240, 240, 245)).save(img, quality=90)

    sources = [E.make_source(pdf_a), E.make_source(pdf_b), E.make_source(img)]
    print(f"sources: {[s.name for s in sources]}")

    # 1) 导出图片
    out_img = os.path.join(TMP, "imgs")
    files = E.export_images(sources, [E.PageRef(0, 0), E.PageRef(1, 1), E.PageRef(2, 0)],
                            out_img, "pic", fmt="png", dpi=120)
    check("导出图片数量", len(files) == 3, str(len(files)))
    sizes = [os.path.getsize(f) for f in files]
    check("导出图片非空", all(s > 2000 for s in sizes), str(sizes))
    with Image.open(files[0]) as im:
        check("图片宽度合理(120dpi)", abs(im.width - 992) <= 2, str(im.size))
    jpgs = E.export_images(sources, [E.PageRef(0, 0)], out_img, "picj", fmt="jpg", dpi=100)
    check("导出 JPG 后缀", jpgs[0].endswith(".jpg"), jpgs[0])

    # 2) 页码 + 水印
    marks = E.Marks(page_numbers=True, number_format="{n}/{total}",
                    watermark="内部资料", watermark_size=60, watermark_opacity=0.12)
    out_mark = os.path.join(TMP, "marked.pdf")
    E._write_refs(sources, [E.PageRef(0, 0), E.PageRef(0, 1)], out_mark, marks=marks)
    doc = pymupdf.open(out_mark)
    txt = doc[0].get_text()
    check("页码写入", "1/2" in txt, repr(txt[:60]))
    check("水印写入", "内部资料" in txt, repr(txt[:60]))
    check("页码页数正确", "2/2" in doc[1].get_text())
    doc.close()

    # 3) 手绘批注
    notes = {
        (0, 0): [annotate.InkStroke([(0.2, 0.3), (0.5, 0.35), (0.7, 0.5)], "#E5484D", 6.0),
                 annotate.TextMark(0.2, 0.6, "手写批注 ABC", "#4F6BFF", "黑体", 0.05)],
    }
    out_note = os.path.join(TMP, "noted.pdf")
    E._write_refs(sources, [E.PageRef(0, 0)], out_note, notes=notes)
    doc = pymupdf.open(out_note)
    check("文字批注写入", "手写批注" in doc[0].get_text(), repr(doc[0].get_text()[:80]))
    check("笔迹产生绘图对象", len(doc[0].get_drawings()) > 0,
          str(len(doc[0].get_drawings())))
    doc.close()

    # 4) 横向拼接
    out_tile = os.path.join(TMP, "tile.pdf")
    E.export_pages(sources, [E.PageRef(0, 0), E.PageRef(1, 0), E.PageRef(0, 1)],
                   "single", TMP, "tile_h", tile="h", per_page=2)
    tile_path = [f for f in os.listdir(TMP) if f.startswith("tile_h")][0]
    doc = pymupdf.open(os.path.join(TMP, tile_path))
    r = doc[0].rect
    check("横向拼接页数(3页→2张)", doc.page_count == 2, str(doc.page_count))
    check("横向拼接宽度≈两页相加", abs(r.width - (595 * 2 + E.TILE_GAP)) <= 1.5,
          f"{r.width:.1f}")
    check("横向拼接高度=单页高", abs(r.height - 842) <= 1.5, f"{r.height:.1f}")
    doc.close()

    # 5) 纵向拼接
    E.export_pages(sources, [E.PageRef(0, 0), E.PageRef(0, 1)], "single", TMP,
                   "tile_v", tile="v", per_page=2)
    vp = [f for f in os.listdir(TMP) if f.startswith("tile_v")][0]
    doc = pymupdf.open(os.path.join(TMP, vp))
    r = doc[0].rect
    check("纵向拼接高度≈两页相加", abs(r.height - (842 * 2 + E.TILE_GAP)) <= 1.5,
          f"{r.height:.1f}")
    doc.close()

    # 6) 压缩
    p1, before, after = E.compress_pdf(pdf_a, os.path.join(TMP, "c_loss.pdf"), "lossless")
    check("无损压缩产出", os.path.exists(p1) and after > 0, f"{before}->{after}")
    p2, before2, after2 = E.compress_pdf(pdf_a, os.path.join(TMP, "c_raster.pdf"),
                                         "raster", dpi=100, quality=60)
    check("重采样压缩产出", os.path.exists(p2), p2)
    doc = pymupdf.open(p2)
    check("重采样后页数不变", doc.page_count == 5, str(doc.page_count))
    doc.close()

    print(f"\n{passed} passed, {len(failed)} failed")
    if failed:
        print("failed:", failed)
    return 0 if not failed else 1


if __name__ == "__main__":
    code = main()
    shutil.rmtree(TMP, ignore_errors=True)
    raise SystemExit(code)
