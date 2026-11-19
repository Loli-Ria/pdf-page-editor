# -*- coding: utf-8 -*-
"""PDF 页数编辑器 · 核心引擎

与界面完全解耦，可单独测试。所有坐标/尺寸单位都是 PDF point（1/72 inch）。
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Callable, Sequence

import pymupdf
from PIL import Image, ImageOps

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
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "PNG")
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
                out_path: str) -> None:
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


def export_pages(sources: Sequence[Source],
                 refs: Sequence[PageRef],
                 mode: str,
                 out_dir: str,
                 prefix: str,
                 group_size: int = 3,
                 progress: ProgressFn | None = None) -> list[str]:
    """从多个来源（PDF / 图片）里挑选页面，按 mode 导出。

    mode:
      each    每个选中页 → 一个 PDF 文件
      single  所有选中页 → 合并成一个 PDF 文件
      every_n 每 N 页 → 一个 PDF 文件
    """
    if not sources:
        raise PdfError("还没有导入任何文件。")
    if not refs:
        raise PdfError("还没有选中任何页面。")
    prefix = safe_filename(prefix)
    os.makedirs(out_dir, exist_ok=True)
    created: list[str] = []

    if mode == "each":
        total = len(refs)
        width = max(3, len(str(total)))
        for i, ref in enumerate(refs):
            out = unique_path(out_dir, f"{prefix}_{str(i + 1).zfill(width)}")
            _write_refs(sources, [ref], out)
            created.append(out)
            _report(progress, (i + 1) * 100 // total, f"正在导出 {i + 1}/{total}")
    elif mode == "single":
        out = unique_path(out_dir, prefix)
        _write_refs(sources, refs, out)
        created.append(out)
        _report(progress, 100, "已合并为 1 个文件")
    elif mode == "every_n":
        n = max(1, int(group_size))
        groups = [refs[i:i + n] for i in range(0, len(refs), n)]
        total = len(groups)
        width = max(2, len(str(total)))
        for gi, group in enumerate(groups):
            out = unique_path(out_dir, f"{prefix}_{str(gi + 1).zfill(width)}")
            _write_refs(sources, group, out)
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
