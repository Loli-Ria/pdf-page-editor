# -*- coding: utf-8 -*-
"""引擎自测：造测试数据 → 拆分 / 合并 → 校验结果。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import pymupdf
from PIL import Image, ImageDraw

from pdf_editor.core import engine as E


def make_pdf(path, n=10):
    doc = pymupdf.open()
    for i in range(n):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"Page {i + 1}", fontsize=48)
        page.insert_text((72, 200), "测试内容 test content", fontsize=20)
    doc.save(path)
    doc.close()


def make_img(path, size, color):
    im = Image.new("RGB", size, color)
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, size[0] - 20, size[1] - 20], outline=(0, 0, 0), width=6)
    im.save(path)


def main():
    tmp = tempfile.mkdtemp(prefix="pdfsplit_")
    src = os.path.join(tmp, "sample.pdf")
    make_pdf(src, 10)
    print("[1] 生成测试 PDF:", src, E.human_size(os.path.getsize(src)))

    # 缩略图
    png = E.render_page_png(src, 0, max_side=200)
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "缩略图不是 PNG"
    print("[2] 缩略图 OK,", len(png), "bytes")

    # 全部拆成单页
    out = os.path.join(tmp, "out_each")
    files = E.split_pdf(src, [E.PageRef(0, i) for i in range(10)], "each", out, "sample")
    assert len(files) == 10, len(files)
    assert all(os.path.exists(f) for f in files)
    assert pymupdf.open(files[0]).page_count == 1
    print("[3] 全部拆分 OK:", len(files), "个文件,", os.path.basename(files[0]))

    # 选 3 页 → 3 个文件，其中一页旋转 90
    out = os.path.join(tmp, "out_three")
    files = E.split_pdf(src, [E.PageRef(0, 2), E.PageRef(0, 5, 90), E.PageRef(0, 7)],
                        "each", out, "pick")
    assert len(files) == 3
    d = pymupdf.open(files[1])
    assert d[0].rotation % 360 == 90, d[0].rotation
    d.close()
    print("[4] 选 3 页拆 3 个文件 OK（含旋转）")

    # 选 3 页 → 合成 1 个文件
    out = os.path.join(tmp, "out_single")
    files = E.split_pdf(src, [E.PageRef(0, 2), E.PageRef(0, 5), E.PageRef(0, 7)],
                        "single", out, "merged3")
    assert len(files) == 1
    d = pymupdf.open(files[0])
    assert d.page_count == 3, d.page_count
    txt = d[0].get_text()
    assert "Page 3" in txt, txt
    d.close()
    print("[5] 选 3 页合 1 个文件 OK")

    # 每 3 页一组
    out = os.path.join(tmp, "out_n")
    files = E.split_pdf(src, [E.PageRef(0, i) for i in range(10)], "every_n",
                        out, "part", group_size=3)
    assert len(files) == 4, len(files)
    d = pymupdf.open(files[-1])
    assert d.page_count == 1
    d.close()
    print("[6] 每 3 页一组 OK:", [os.path.basename(f) for f in files])

    # 合并：PDF + 图片（竖图 / 横图 / 透明 PNG）
    img1 = os.path.join(tmp, "a_vertical.jpg")
    img2 = os.path.join(tmp, "b_wide.jpg")
    img3 = os.path.join(tmp, "c_alpha.png")
    make_img(img1, (1200, 1800), (200, 220, 255))
    make_img(img2, (2000, 900), (255, 230, 200))
    im = Image.new("RGBA", (800, 800), (255, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([100, 100, 700, 700], fill=(0, 160, 90, 255))
    im.save(img3)

    items = [E.MergeItem(img1, "image"), E.MergeItem(src, "pdf"),
             E.MergeItem(img2, "image"), E.MergeItem(img3, "image")]
    out_pdf = os.path.join(tmp, "merged.pdf")
    E.merge_to_pdf(items, out_pdf, image_mode="a4")
    d = pymupdf.open(out_pdf)
    assert d.page_count == 13, d.page_count
    r = d[0].rect
    assert abs(r.width - 595) < 1 and abs(r.height - 842) < 1, r
    print("[7] A4 合并 OK: 13 页, 首页", round(r.width), "x", round(r.height))

    out_pdf2 = os.path.join(tmp, "merged_orig.pdf")
    E.merge_to_pdf([E.MergeItem(img1, "image")], out_pdf2,
                   image_mode="original", dpi=200)
    d2 = pymupdf.open(out_pdf2)
    print("[8] 原尺寸合并 OK:", round(d2[0].rect.width), "x", round(d2[0].rect.height))
    d2.close()
    d.close()

    # 不覆盖同名
    out = os.path.join(tmp, "out_each")
    files2 = E.split_pdf(src, [E.PageRef(0, 0)], "single", out, "sample")
    assert files2[0] != files[0]
    print("[9] 同名不覆盖 OK:", os.path.basename(files2[0]))

    print("\n全部通过。临时目录:", tmp)



    # 多来源：两个 PDF + 一张图片，跨文件选页导出
    src2 = os.path.join(tmp, "second.pdf")
    doc2 = pymupdf.open()
    for i in range(4):
        pg = doc2.new_page(width=400, height=600)
        pg.insert_text((40, 80), f"Second {i + 1}", fontsize=30)
    doc2.save(src2)
    doc2.close()

    s1 = E.make_source(src)
    s2 = E.make_source(src2)
    s3 = E.make_source(img1)
    assert (s1.page_count, s2.page_count, s3.page_count) == (10, 4, 1)
    assert s3.kind == "image"
    sources = [s1, s2, s3]

    out = os.path.join(tmp, "out_multi")
    files = E.export_pages(sources, [E.PageRef(0, 1), E.PageRef(1, 2), E.PageRef(2, 0)],
                           "single", out, "cross")
    assert len(files) == 1, files
    dm = pymupdf.open(files[0])
    assert dm.page_count == 3, dm.page_count
    assert "Page 2" in dm[0].get_text(), dm[0].get_text()
    assert "Second 3" in dm[1].get_text(), dm[1].get_text()
    r = dm[2].rect
    assert abs(r.width - 595) < 1 and abs(r.height - 842) < 1, r
    dm.close()
    print("[10] 多来源合成 OK: 3 页(2 PDF + 1 图片), 图片页 A4")

    out = os.path.join(tmp, "out_multi_each")
    files = E.export_pages(sources, [E.PageRef(0, 9), E.PageRef(1, 0)],
                           "each", out, "mx")
    assert len(files) == 2, files
    d0 = pymupdf.open(files[0])
    d1 = pymupdf.open(files[1])
    assert "Page 10" in d0[0].get_text(), d0[0].get_text()
    assert "Second 1" in d1[0].get_text(), d1[0].get_text()
    d0.close()
    d1.close()
    print("[11] 多来源逐页 OK:", [os.path.basename(f) for f in files])

    out = os.path.join(tmp, "out_multi_grp")
    files = E.export_pages(sources, [E.PageRef(0, 0), E.PageRef(0, 1),
                                     E.PageRef(1, 0), E.PageRef(2, 0)],
                           "every_n", out, "grp", group_size=3)
    assert len(files) == 2, files
    print("[12] 多来源每 3 页一组 OK:", [os.path.basename(f) for f in files])

    # 缩略图：图片来源也能渲染
    png = E.render_ref_png(sources, E.PageRef(2, 0), max_side=180)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    png = E.render_ref_png(sources, E.PageRef(1, 3, 90), max_side=180)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    print("[13] 多来源缩略图 OK:", len(png), "bytes")


if __name__ == "__main__":
    main()
