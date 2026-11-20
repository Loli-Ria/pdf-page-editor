# -*- coding: utf-8 -*-
"""PDF 页数编辑器 · 核心引擎

与界面完全解耦，可单独测试。所有坐标/尺寸单位都是 PDF point（1/72 inch）。
"""

from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from typing import Callable, Sequence

import pymupdf
from PIL import Image, ImageOps

from . import annotate

A4_W, A4_H = pymupdf.paper_size("a4")  # 595.0 x 842.0

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif"}

ProgressFn = Callable[[int, str], None]


class PdfError(Exception):
    """面向用户的可读错误。"""


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------

def _report(cb: ProgressFn | None, pct: int, msg: str) -> None:
    if cb:
        cb(max(0, min(100, int(pct))), msg)


def natural_key(text: str):
    """让 1.jpg, 2.jpg, 10.jpg 按人眼顺序排。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name).strip(" .")
    return name or "output"


def unique_path(folder: str, stem: str, ext: str = ".pdf") -> str:
    path = os.path.join(folder, stem + ext)
    if not os.path.exists(path):
        return path
    n = 2
    while True:
        path = os.path.join(folder, f"{stem} ({n}){ext}")
        if not os.path.exists(path):
            return path
        n += 1


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} GB"


# --------------------------------------------------------------------------
# 文档
# --------------------------------------------------------------------------

@dataclass
class Source:
    """一个来源文件：PDF 或图片。图片恒为 1 页。"""
    path: str
    kind: str                  # "pdf" | "image"
    page_count: int = 1
    size: int = 0

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def stem(self) -> str:
        return os.path.splitext(self.name)[0]


@dataclass
class PageRef:
    """逻辑上的一页：第 src 个来源文件的第 index 页（0 基），额外旋转 rotation 度。"""
    src: int = 0
    index: int = 0
    rotation: int = 0


def make_source(path: str) -> Source:
    """校验并登记一个来源文件，失败抛 PdfError。"""
    if not os.path.isfile(path):
        raise PdfError(f"文件不存在：{path}")
    kind = kind_of(path)
    if kind is None:
        raise PdfError(f"不支持的文件类型：{os.path.basename(path)}")
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if kind == "pdf":
        return Source(path, "pdf", pdf_page_count(path), size)
    try:
        image_info(path)
    except Exception as exc:  # noqa: BLE001
        raise PdfError(f"无法读取图片：{os.path.basename(path)}\n{exc}") from exc
    return Source(path, "image", 1, size)


def open_pdf(path: str) -> pymupdf.Document:
    if not os.path.isfile(path):
        raise PdfError(f"文件不存在：{path}")
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001
        raise PdfError(f"无法打开 PDF：{os.path.basename(path)}\n{exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise PdfError(f"「{os.path.basename(path)}」设置了打开密码，暂不支持加密文档。")
    if doc.page_count == 0:
        doc.close()
        raise PdfError(f"「{os.path.basename(path)}」没有任何页面。")
    return doc


def pdf_page_count(path: str) -> int:
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def render_page_png(path: str, index: int, rotation: int = 0,
                    max_side: int = 240) -> bytes:
    """把某一页渲染成 PNG 字节，长边不超过 max_side 像素。"""
    doc = pymupdf.open(path)
    try:
        if index < 0 or index >= doc.page_count:
            raise PdfError(f"页码越界：{index + 1}")
        page = doc[index]
        if rotation:
            page.set_rotation((page.rotation + rotation) % 360)
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            raise PdfError("页面尺寸异常。")
        zoom = max_side / max(rect.width, rect.height)
        zoom = max(0.02, min(zoom, 6.0))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


# --------------------------------------------------------------------------
# 拆分
# --------------------------------------------------------------------------

def render_ref_png(sources: Sequence[Source], ref: PageRef,
                   max_side: int = 240) -> bytes:
    """按 PageRef 渲染缩略图，来源可以是 PDF 页，也可以是图片。"""
    if not (0 <= ref.src < len(sources)):
        raise PdfError("页面来源无效。")
    src = sources[ref.src]
    if src.kind == "pdf":
        return render_page_png(src.path, ref.index, ref.rotation, max_side)
    im = _load_image_rgb(src.path)
    try:
        if ref.rotation:
            im = im.rotate(-ref.rotation, expand=True)
        # 图片导出时会被放进 A4 白底页，预览也照这个来，批注位置才对得上
        w = max(1, int(round(max_side * A4_W / A4_H)))
        h = max(1, int(max_side))
        canvas = Image.new("RGB", (w, h), (255, 255, 255))
        thumb = im.copy()
        thumb.thumbnail((w, h), Image.LANCZOS)
        canvas.paste(thumb, ((w - thumb.width) // 2, (h - thumb.height) // 2))
        thumb.close()
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        canvas.close()
        return buf.getvalue()
    finally:
        im.close()

def _write_pages(src_doc: pymupdf.Document, refs: Sequence[PageRef], out_path: str) -> None:
    dst = pymupdf.open()
    try:
        for ref in refs:
            dst.insert_pdf(src_doc, from_page=ref.index, to_page=ref.index)
            page = dst[-1]
            if ref.rotation:
                page.set_rotation((page.rotation + ref.rotation) % 360)
        dst.save(out_path, garbage=3, deflate=True)
    finally:
        dst.close()


def _write_refs(sources: Sequence[Source], refs: Sequence[PageRef],
                out_path: str, marks: "Marks | None" = None,
                notes: dict | None = None) -> None:
    """把若干跨文件的 PageRef 写进一个新 PDF。"""
    dst = pymupdf.open()
    cache: dict[str, pymupdf.Document] = {}
    try:
        for ref in refs:
            src = sources[ref.src]
            if src.kind == "pdf":
                doc = cache.get(src.path)
                if doc is None:
                    doc = open_pdf(src.path)
                    cache[src.path] = doc
                dst.insert_pdf(doc, from_page=ref.index, to_page=ref.index)
                if ref.rotation:
                    page = dst[-1]
                    page.set_rotation((page.rotation + ref.rotation) % 360)
            else:
                _append_image_page(dst, src.path, "a4", 200, ref.rotation)
            _draw_notes(dst[-1], (notes or {}).get((ref.src, ref.index)))
        if dst.page_count == 0:
            raise PdfError("结果里没有任何页面。")
        _apply_marks(dst, marks)
        dst.save(out_path, garbage=3, deflate=True)
    finally:
        for doc in cache.values():
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass
        dst.close()


def export_pages(sources: Sequence[Source],
                 refs: Sequence[PageRef],
                 mode: str,
                 out_dir: str,
                 prefix: str,
                 group_size: int = 3,
                 progress: ProgressFn | None = None,
                 marks: "Marks | None" = None,
                 notes: dict | None = None,
                 tile: str = "none",
                 per_page: int = 2) -> list[str]:
    """从多个来源（PDF / 图片）里挑选页面，按 mode 导出。

    mode:
      each    每个选中页 → 一个 PDF 文件
      single  所有选中页 → 合并成一个 PDF 文件
      every_n 每 N 页 → 一个 PDF 文件
    tile:
      none 原样输出；h 每 per_page 页左右并排；v 每 per_page 页上下堆叠
    """
    if not sources:
        raise PdfError("还没有导入任何文件。")
    if not refs:
        raise PdfError("还没有选中任何页面。")
    prefix = safe_filename(prefix)
    os.makedirs(out_dir, exist_ok=True)
    created: list[str] = []
    tile = tile if tile in ("h", "v") else "none"

    def emit(group: Sequence[PageRef], out: str) -> None:
        if tile == "none":
            _write_refs(sources, group, out, marks=marks, notes=notes)
        else:
            _write_tiled(sources, group, out, tile, per_page, marks, notes)

    if mode == "each":
        total = len(refs)
        width = max(3, len(str(total)))
        for i, ref in enumerate(refs):
            out = unique_path(out_dir, f"{prefix}_{str(i + 1).zfill(width)}")
            emit([ref], out)
            created.append(out)
            _report(progress, (i + 1) * 100 // total, f"正在导出 {i + 1}/{total}")
    elif mode == "single":
        out = unique_path(out_dir, prefix)
        emit(refs, out)
        created.append(out)
        _report(progress, 100, "已合并为 1 个文件")
    elif mode == "every_n":
        n = max(1, int(group_size))
        groups = [refs[i:i + n] for i in range(0, len(refs), n)]
        total = len(groups)
        width = max(2, len(str(total)))
        for gi, group in enumerate(groups):
            out = unique_path(out_dir, f"{prefix}_{str(gi + 1).zfill(width)}")
            emit(group, out)
            created.append(out)
            _report(progress, (gi + 1) * 100 // total,
                    f"正在导出第 {gi + 1}/{total} 组")
    else:
        raise PdfError(f"未知的拆分方式：{mode}")
    return created


def split_pdf(src: str,
              pages: Sequence[PageRef],
              mode: str,
              out_dir: str,
              prefix: str,
              group_size: int = 3,
              progress: ProgressFn | None = None) -> list[str]:
    """单文件拆分的便捷入口（保留给测试与旧调用）。"""
    source = make_source(src)
    refs = [PageRef(0, p.index, p.rotation) for p in pages]
    return export_pages([source], refs, mode, out_dir, prefix, group_size, progress)


# --------------------------------------------------------------------------
# 合并（PDF + 图片）
# --------------------------------------------------------------------------

@dataclass
class MergeItem:
    path: str
    kind: str  # "pdf" | "image"


def kind_of(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def _load_image_rgb(path: str) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P", "PA"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            return bg
        if im.mode != "RGB":
            im = im.convert("RGB")
        return im.copy()


def render_image_thumb(path: str, max_side: int = 240) -> bytes:
    """图片缩略图（已处理 EXIF 方向）。"""
    im = _load_image_rgb(path)
    try:
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()
    finally:
        im.close()


def image_info(path: str) -> tuple[int, int]:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return im.size


def _append_image_page(doc: pymupdf.Document, path: str,
                       mode: str = "a4", dpi: int = 200,
                       rotation: int = 0) -> None:
    im = _load_image_rgb(path)
    try:
        if rotation:
            im = im.rotate(-rotation, expand=True)
        w, h = im.size
        if w <= 0 or h <= 0:
            raise PdfError(f"图片尺寸无效：{os.path.basename(path)}")
        buf = io.BytesIO()
        if mode == "a4":
            max_w, max_h = int(A4_W / 72 * 300), int(A4_H / 72 * 300)
            if w > max_w or h > max_h:
                im.thumbnail((max_w, max_h), Image.LANCZOS)
                w, h = im.size
            im.save(buf, "JPEG", quality=88, optimize=True)
            page = doc.new_page(width=A4_W, height=A4_H)
            scale = min(A4_W / w, A4_H / h)
            dw, dh = w * scale, h * scale
            x0, y0 = (A4_W - dw) / 2, (A4_H - dh) / 2
            page.insert_image(pymupdf.Rect(x0, y0, x0 + dw, y0 + dh),
                              stream=buf.getvalue())
        else:  # original
            im.save(buf, "JPEG", quality=92, optimize=True)
            page_w = w * 72.0 / max(1, dpi)
            page_h = h * 72.0 / max(1, dpi)
            page = doc.new_page(width=page_w, height=page_h)
            page.insert_image(pymupdf.Rect(0, 0, page_w, page_h), stream=buf.getvalue())
    finally:
        im.close()


def merge_to_pdf(items: Sequence[MergeItem],
                 out_path: str,
                 image_mode: str = "a4",
                 dpi: int = 200,
                 progress: ProgressFn | None = None) -> str:
    if not items:
        raise PdfError("还没有添加任何文件。")
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    doc = pymupdf.open()
    try:
        total = len(items)
        for i, it in enumerate(items):
            if it.kind == "pdf":
                src = open_pdf(it.path)
                try:
                    doc.insert_pdf(src)
                finally:
                    src.close()
            elif it.kind == "image":
                _append_image_page(doc, it.path, image_mode, dpi)
            else:
                raise PdfError(f"不支持的文件类型：{os.path.basename(it.path)}")
            _report(progress, (i + 1) * 100 // total,
                    f"正在处理 {i + 1}/{total}：{os.path.basename(it.path)}")
        if doc.page_count == 0:
            raise PdfError("结果里没有任何页面。")
        doc.save(out_path, garbage=3, deflate=True)
    finally:
        doc.close()
    return out_path


def estimate_pages(items: Sequence[MergeItem]) -> int:
    total = 0
    for it in items:
        if it.kind == "pdf":
            try:
                total += pdf_page_count(it.path)
            except PdfError:
                pass
        else:
            total += 1
    return total


# --------------------------------------------------------------------------
# 页码 / 水印
# --------------------------------------------------------------------------

@dataclass
class Marks:
    """页码与文字水印的设置，导出时叠加到每一页。"""

    page_numbers: bool = False
    number_format: str = "{n} / {total}"
    number_pos: str = "bottom-center"   # bottom-center / bottom-right / bottom-left
    number_size: float = 10.0
    number_color: str = "#6C7688"
    watermark: str = ""
    watermark_size: float = 46.0
    watermark_color: str = "#1A2030"
    watermark_opacity: float = 0.10

    def active(self) -> bool:
        return self.page_numbers or bool(self.watermark.strip())


def _apply_marks(doc: pymupdf.Document, marks: Marks | None) -> None:
    """在文档每一页写上页码 / 水印。"""
    if not marks or not marks.active():
        return
    total = doc.page_count
    for i, page in enumerate(doc):
        r = page.rect
        if marks.watermark.strip():
            page.insert_textbox(
                r, marks.watermark,
                fontname="china-s", fontsize=marks.watermark_size,
                color=annotate.hex_to_rgb(marks.watermark_color),
                fill_opacity=marks.watermark_opacity,
                align=pymupdf.TEXT_ALIGN_CENTER,
                rotate=0, overlay=True,
            )
        if marks.page_numbers:
            text = (marks.number_format
                    .replace("{n}", str(i + 1))
                    .replace("{total}", str(total)))
            size = marks.number_size
            band = min(36.0, r.height * 0.06)
            if marks.number_pos == "bottom-right":
                rect = pymupdf.Rect(r.x1 - 220, r.y1 - band, r.x1 - 24, r.y1 - 6)
                align = pymupdf.TEXT_ALIGN_RIGHT
            elif marks.number_pos == "bottom-left":
                rect = pymupdf.Rect(r.x0 + 24, r.y1 - band, r.x0 + 220, r.y1 - 6)
                align = pymupdf.TEXT_ALIGN_LEFT
            else:
                rect = pymupdf.Rect(r.x0 + 24, r.y1 - band, r.x1 - 24, r.y1 - 6)
                align = pymupdf.TEXT_ALIGN_CENTER
            page.insert_textbox(rect, text, fontname="china-s", fontsize=size,
                                color=annotate.hex_to_rgb(marks.number_color),
                                align=align, overlay=True)


def _draw_notes(page: pymupdf.Page, notes: Sequence[object] | None) -> None:
    """把这一页的手绘笔迹与文字贴上去。"""
    if not notes:
        return
    strokes = [n for n in notes if isinstance(n, annotate.InkStroke)]
    texts = [n for n in notes if isinstance(n, annotate.TextMark)]
    annotate.draw_strokes(page, strokes)
    annotate.draw_texts(page, texts)


# --------------------------------------------------------------------------
# 拼接（两页并成一页）
# --------------------------------------------------------------------------

TILE_GAP = 6.0
IMAGE_DPI_ASSUMED = 200.0


def _ref_size(sources: Sequence[Source], ref: PageRef,
              cache: dict[str, pymupdf.Document] | None = None) -> tuple[float, float]:
    """一页在 PDF 里应占的宽高（point），已考虑旋转。"""
    src = sources[ref.src]
    if src.kind == "pdf":
        doc = None
        if cache is not None:
            doc = cache.get(src.path)
        if doc is None:
            doc = open_pdf(src.path)
            if cache is not None:
                cache[src.path] = doc
        r = doc[ref.index].rect
        w, h = r.width, r.height
    else:
        pw, ph = image_info(src.path)
        w, h = pw * 72.0 / IMAGE_DPI_ASSUMED, ph * 72.0 / IMAGE_DPI_ASSUMED
    if ref.rotation % 180:
        w, h = h, w
    return w, h


def _place_ref(dst: pymupdf.Document, page: pymupdf.Page, rect: pymupdf.Rect,
               sources: Sequence[Source], ref: PageRef,
               cache: dict[str, pymupdf.Document]) -> None:
    """把一页内容摆到 rect 里。"""
    src = sources[ref.src]
    if src.kind == "pdf":
        doc = cache.get(src.path)
        if doc is None:
            doc = open_pdf(src.path)
            cache[src.path] = doc
        page.show_pdf_page(rect, doc, ref.index, keep_proportion=True,
                           rotate=ref.rotation % 360, overlay=True)
    else:
        page.insert_image(rect, filename=src.path, keep_proportion=True,
                          rotate=ref.rotation % 360, overlay=True)


def _write_tiled(sources: Sequence[Source], refs: Sequence[PageRef], out_path: str,
                 direction: str, per_page: int, marks: Marks | None,
                 notes: dict | None) -> None:
    """每 per_page 页拼成一张：h=左右并排，v=上下堆叠。"""
    dst = pymupdf.open()
    cache: dict[str, pymupdf.Document] = {}
    step = max(1, int(per_page))
    try:
        for start in range(0, len(refs), step):
            chunk = list(refs[start:start + step])
            sizes = [_ref_size(sources, r, cache) for r in chunk]
            if direction == "h":
                w = sum(s[0] for s in sizes) + TILE_GAP * (len(chunk) - 1)
                h = max(s[1] for s in sizes)
            else:
                w = max(s[0] for s in sizes)
                h = sum(s[1] for s in sizes) + TILE_GAP * (len(chunk) - 1)
            page = dst.new_page(width=w, height=h)
            x = y = 0.0
            for ref, (pw, ph) in zip(chunk, sizes):
                rect = pymupdf.Rect(x, y, x + pw, y + ph)
                _place_ref(dst, page, rect, sources, ref, cache)
                _draw_notes(page, (notes or {}).get((ref.src, ref.index)))
                if direction == "h":
                    x += pw + TILE_GAP
                else:
                    y += ph + TILE_GAP
        _apply_marks(dst, marks)
        if dst.page_count == 0:
            raise PdfError("结果里没有任何页面。")
        dst.save(out_path, garbage=3, deflate=True)
    finally:
        for doc in cache.values():
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass
        dst.close()


# --------------------------------------------------------------------------
# 压缩
# --------------------------------------------------------------------------

def compress_pdf(src_path: str, out_path: str, mode: str = "lossless",
                 dpi: int = 150, quality: int = 70,
                 progress: ProgressFn | None = None) -> tuple[str, int, int]:
    """压缩 PDF。返回 (输出路径, 原大小, 新大小)。

    mode="lossless" 只做无损清理；mode="raster" 把每页重新采样成 JPEG（明显变小，文字不再可选中）。
    """
    if not os.path.exists(src_path):
        raise PdfError("文件不存在。")
    before = os.path.getsize(src_path)
    doc = open_pdf(src_path)
    try:
        if mode == "raster":
            out = pymupdf.open()
            try:
                total = doc.page_count
                for i, page in enumerate(doc):
                    pix = page.get_pixmap(dpi=max(36, int(dpi)))
                    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=int(quality), optimize=True)
                    buf.seek(0)
                    new_page = out.new_page(width=page.rect.width, height=page.rect.height)
                    new_page.insert_image(new_page.rect, stream=buf.getvalue())
                    _report(progress, (i + 1) * 100 // max(1, total),
                            f"正在压缩 {i + 1}/{total}")
                out.save(out_path, garbage=4, deflate=True, clean=True)
            finally:
                out.close()
        else:
            _report(progress, 40, "正在清理无用对象")
            doc.save(out_path, garbage=4, deflate=True, clean=True)
            _report(progress, 100, "完成")
    finally:
        doc.close()
    after = os.path.getsize(out_path)
    return out_path, before, after


# --------------------------------------------------------------------------
# 导出为图片
# --------------------------------------------------------------------------

def export_images(sources: Sequence[Source],
                  refs: Sequence[PageRef],
                  out_dir: str,
                  prefix: str,
                  fmt: str = "png",
                  dpi: int = 150,
                  quality: int = 90,
                  marks: Marks | None = None,
                  notes: dict | None = None,
                  progress: ProgressFn | None = None) -> list[str]:
    """把选中的页逐页导出成 PNG / JPG。"""
    if not sources:
        raise PdfError("还没有导入任何文件。")
    if not refs:
        raise PdfError("还没有选中任何页面。")
    fmt = "jpg" if str(fmt).lower() in ("jpg", "jpeg") else "png"
    prefix = safe_filename(prefix)
    os.makedirs(out_dir, exist_ok=True)
    created: list[str] = []
    total = len(refs)
    width = max(3, len(str(total)))
    tmp_dir = tempfile.mkdtemp(prefix="pdfimg_")
    try:
        for i, ref in enumerate(refs):
            one = os.path.join(tmp_dir, f"p{i}.pdf")
            _write_refs(sources, [ref], one, marks=marks, notes=notes)
            doc = open_pdf(one)
            try:
                page = doc[0]
                pix = page.get_pixmap(dpi=max(36, int(dpi)))
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                out = unique_path(out_dir, f"{prefix}_{str(i + 1).zfill(width)}",
                                  "." + fmt)
                if fmt == "jpg":
                    img.convert("RGB").save(out, format="JPEG",
                                            quality=int(quality), optimize=True)
                else:
                    img.save(out, format="PNG", optimize=True)
            finally:
                doc.close()
            created.append(out)
            _report(progress, (i + 1) * 100 // total, f"正在导出 {i + 1}/{total}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return created
