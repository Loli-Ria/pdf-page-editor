# -*- coding: utf-8 -*-
"""拆分页：上传 PDF → 勾选页面 → 三种出法。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from ..core import annotate
from ..core import engine as E
from . import theme
from .widgets import (DropZone, FileChip, FlowLayout, RadioCardGroup, SidePanel,
                      hint_card)
from .page_grid import PageGrid
from .preview_panel import PreviewPanel

FILTER = "PDF 和图片 (*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.gif)"

# 源文件标签的尺寸约定：单行高、间距、最多显示几行
CHIP_H = 30
CHIP_GAP = 8
CHIP_ROWS = 2

# 预览栏的宽度约束：拖拽时不能挤死中间的缩略图区
PREVIEW_MIN = 260
PREVIEW_DEFAULT = 360
PREVIEW_MAX = 620
PREVIEW_RATIO = 0.46      # 最多占可用宽度的比例
LEFT_MIN = 380            # 中间缩略图区的最小宽度
SIDE_W = 344              # 右侧参数面板固定宽度


class _SplitWorker(QThread):
    progress = Signal(int, str)
    ok = Signal(list)
    err = Signal(str)

    def __init__(self, sources, refs, mode: str, out_dir: str,
                 prefix: str, group_size: int, fmt: str = "pdf",
                 dpi: int = 150, quality: int = 90, marks=None, notes=None,
                 tile: str = "none", per_page: int = 2,
                 compress: tuple | None = None) -> None:
        super().__init__()
        self.sources = list(sources)
        self.refs = refs
        self.mode = mode
        self.out_dir = out_dir
        self.prefix = prefix
        self.group_size = group_size
        self.fmt = fmt
        self.dpi = dpi
        self.quality = quality
        self.marks = marks
        self.notes = notes
        self.tile = tile
        self.per_page = per_page
        self.compress = compress

    def run(self) -> None:
        try:
            if self.fmt in ("png", "jpg"):
                files = E.export_images(self.sources, self.refs, self.out_dir,
                                        self.prefix, fmt=self.fmt, dpi=self.dpi,
                                        quality=self.quality, marks=self.marks,
                                        notes=self.notes,
                                        progress=self.progress.emit)
            else:
                files = E.export_pages(self.sources, self.refs, self.mode,
                                       self.out_dir, self.prefix, self.group_size,
                                       self.progress.emit, marks=self.marks,
                                       notes=self.notes, tile=self.tile,
                                       per_page=self.per_page)
            if self.compress:
                mode, dpi, quality = self.compress
                total = len(files)
                for i, f in enumerate(files):
                    self.progress.emit(int(i * 100 / max(1, total)), "正在压缩…")
                    tmp = f + ".tmp.pdf"
                    try:
                        E.compress_pdf(f, tmp, mode, dpi, quality)
                        os.replace(tmp, f)
                    except Exception:  # noqa: BLE001
                        if os.path.exists(tmp):
                            os.remove(tmp)
            self.ok.emit(files)
        except Exception as exc:  # noqa: BLE001
            self.err.emit(str(exc))


def _section_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("SectionTitle")
    return lab


class SplitPage(QWidget):
    toast = Signal(str, str)   # 文本, 类型(info/ok/error)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.sources: list[E.Source] = []
        self._worker: _SplitWorker | None = None
        self._last_out = ""
        # 批注草稿：(源序号, 页序号) → [InkStroke | TextMark]
        self.notes: dict[tuple[int, int], list] = {}
        self._undo_stack: list[tuple[tuple[int, int], object]] = []
        self.setAcceptDrops(True)
        self._build()
        self._refresh_state()
        sc = QShortcut(QKeySequence("Ctrl+Z"), self)
        sc.setContext(Qt.WidgetWithChildrenShortcut)
        sc.activated.connect(self._undo_note)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(16)

        # ---------------- 左：文件 + 缩略图
        left = QVBoxLayout()
        left.setSpacing(12)

        self.src_card = QFrame()
        self.src_card.setObjectName("Card")
        sc = QVBoxLayout(self.src_card)
        sc.setContentsMargins(16, 10, 16, 12)
        sc.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        head_title = QLabel("源文件")
        head_title.setObjectName("SectionTitle")
        self.src_count = QLabel("0 个文件 · 0 页")
        self.src_count.setObjectName("Hint")
        self.btn_pick = QPushButton("添加文件")
        self.btn_pick.setObjectName("Ghost")
        self.btn_pick.setCursor(Qt.PointingHandCursor)
        head.addWidget(head_title)
        head.addWidget(self.src_count)
        head.addStretch(1)
        head.addWidget(self.btn_pick)
        sc.addLayout(head)

        # 源文件标签：最多两行，超出的在框内滚动（不抢缩略图的位置）
        self.chip_host = QWidget()
        self.chip_flow = FlowLayout(self.chip_host, 0, CHIP_GAP, CHIP_GAP)
        self.chip_scroll = QScrollArea()
        self.chip_scroll.setObjectName("ChipScroll")
        self.chip_scroll.setFrameShape(QFrame.NoFrame)
        self.chip_scroll.setWidgetResizable(False)
        self.chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.chip_scroll.setWidget(self.chip_host)
        self.chip_scroll.setFixedHeight(0)
        sc.addWidget(self.chip_scroll)

        self.src_empty = QLabel("把 PDF 或图片拖进来，可以一次拖多个")
        self.src_empty.setObjectName("Faint")
        sc.addWidget(self.src_empty)
        left.addWidget(self.src_card)

        # 工具行（自动换行：窗口变窄时按钮会折到下一行，不会互相挤压）
        self.tools = QWidget()
        tl = FlowLayout(self.tools, 0, 8, 8)

        def ghost(text: str, tip: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.setCursor(Qt.PointingHandCursor)
            if tip:
                b.setToolTip(tip)
            return b

        self.btn_all = ghost("全选")
        self.btn_inv = ghost("反选")
        self.btn_none = ghost("清空")
        self.btn_rot = ghost("转 90°", "把当前页顺时针旋转 90°（可连点）")
        self.btn_del = ghost("删除", "从列表里移除当前页（不勾选即不输出）")

        self.count_label = QLabel("已选 0 / 0 页")
        self.count_label.setObjectName("Hint")
        self.count_label.setMinimumWidth(92)

        self.btn_zoom_s = ghost("－", "缩小缩略图")
        self.btn_zoom_l = ghost("＋", "放大缩略图")
        for b in (self.btn_zoom_s, self.btn_zoom_l):
            b.setFixedWidth(34)

        for w in (self.btn_all, self.btn_inv, self.btn_none, self.btn_rot,
                  self.btn_del, self.count_label, self.btn_zoom_s,
                  self.btn_zoom_l):
            tl.addWidget(w)
        left.addWidget(self.tools)

        # 缩略图区
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid = PageGrid()
        self.grid.set_scroll_area(self.scroll)
        self.scroll.setWidget(self.grid)

        # 空态
        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.addStretch(1)
        self.drop = DropZone("把 PDF 或图片拖到这里",
                             "或者点击这里选择 · 可以一次加多个文件")
        self.drop.setMaximumWidth(620)
        self.drop.setMinimumHeight(180)
        ev.addWidget(self.drop, 0, Qt.AlignHCenter)
        ev.addSpacing(10)
        tip = QLabel("多个文件的页面会按导入顺序排在一起，勾选后可以逐页拆、合并成一份，或每 N 页一组")
        tip.setObjectName("Faint")
        tip.setAlignment(Qt.AlignCenter)
        ev.addWidget(tip)
        ev.addStretch(1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.scroll)
        left.addWidget(self.stack, 1)

        # ---------------- 最左：大预览（宽度可拖拽调整，有上下限）
        self.preview = PreviewPanel()
        self.preview.setMinimumWidth(PREVIEW_MIN)
        self.preview.clear()

        left_host = QWidget()
        left_host.setLayout(left)
        left_host.setMinimumWidth(LEFT_MIN)

        self.split = QSplitter(Qt.Horizontal)
        self.split.setObjectName("MainSplit")
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(10)
        self.split.addWidget(self.preview)
        self.split.addWidget(left_host)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([PREVIEW_DEFAULT, 900])
        root.addWidget(self.split, 1)

        # ---------------- 右：参数面板（内容可滚动，窗口变小时不会互相压住）
        side = SidePanel(344)
        rv = side.v

        card1 = QFrame()
        card1.setObjectName("Card")
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(16, 14, 16, 16)
        c1.setSpacing(10)
        c1.addWidget(_section_label("输出方式"))

        self.mode_group = RadioCardGroup()
        self.mode_group.add_card("每页一个文件", "勾选的每一页各存成一个 PDF")
        self.mode_group.add_card("合成一个文件", "勾选的页按顺序合并成一个 PDF")
        self.mode_group.add_card("每 N 页一组", "按顺序每 N 页合成一个 PDF")
        c1.addWidget(self.mode_group)

        self.n_row = QWidget()
        nr = QHBoxLayout(self.n_row)
        nr.setContentsMargins(2, 0, 2, 0)
        nr.setSpacing(8)
        nr.addWidget(QLabel("每"))
        self.n_spin = QSpinBox()
        self.n_spin.setRange(1, 999)
        self.n_spin.setValue(3)
        self.n_spin.setFixedWidth(78)
        nr.addWidget(self.n_spin)
        nr.addWidget(QLabel("页合成一个文件"))
        nr.addStretch(1)
        c1.addWidget(self.n_row)
        self.n_row.setVisible(False)
        self.mode_group.changed.connect(
            lambda i: self.n_row.setVisible(i == 2))
        rv.addWidget(card1)

        # ---- 附加处理：导出格式 / 页码 / 水印 / 拼接 / 压缩
        card1b = QFrame()
        card1b.setObjectName("Card")
        cb = QVBoxLayout(card1b)
        cb.setContentsMargins(16, 14, 16, 16)
        cb.setSpacing(9)
        cb.addWidget(_section_label("附加处理"))

        row_fmt = QHBoxLayout()
        row_fmt.setSpacing(8)
        row_fmt.addWidget(QLabel("导出为"))
        self.fmt_box = QComboBox()
        self.fmt_box.addItems(["PDF 文件", "PNG 图片", "JPG 图片"])
        row_fmt.addWidget(self.fmt_box, 1)
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 600)
        self.dpi_spin.setValue(150)
        self.dpi_spin.setSuffix(" dpi")
        self.dpi_spin.setFixedWidth(96)
        row_fmt.addWidget(self.dpi_spin)
        cb.addLayout(row_fmt)

        self.chk_num = QCheckBox("加页码")
        cb.addWidget(self.chk_num)
        self.num_edit = QLineEdit("{n} / {total}")
        self.num_edit.setToolTip("{n} 是当前页，{total} 是总页数")
        self.num_edit.setVisible(False)
        cb.addWidget(self.num_edit)

        self.chk_wm = QCheckBox("加文字水印")
        cb.addWidget(self.chk_wm)
        self.wm_edit = QLineEdit()
        self.wm_edit.setPlaceholderText("例如 内部资料")
        self.wm_edit.setVisible(False)
        cb.addWidget(self.wm_edit)

        row_tile = QHBoxLayout()
        row_tile.setSpacing(8)
        row_tile.addWidget(QLabel("拼接"))
        self.tile_box = QComboBox()
        self.tile_box.addItems(["不拼接", "左右并排", "上下堆叠"])
        row_tile.addWidget(self.tile_box, 1)
        self.per_spin = QSpinBox()
        self.per_spin.setRange(2, 8)
        self.per_spin.setValue(2)
        self.per_spin.setFixedWidth(64)
        self.per_spin.setSuffix(" 页")
        self.per_spin.setToolTip("每张拼几页")
        self.per_spin.setVisible(False)
        row_tile.addWidget(self.per_spin)
        cb.addLayout(row_tile)

        self.chk_zip = QCheckBox("压缩输出")
        cb.addWidget(self.chk_zip)
        self.zip_row = QWidget()
        zr = QHBoxLayout(self.zip_row)
        zr.setContentsMargins(0, 0, 0, 0)
        zr.setSpacing(8)
        self.zip_box = QComboBox()
        self.zip_box.addItems(["无损清理", "重新采样（更小）"])
        zr.addWidget(self.zip_box, 1)
        self.zip_q = QSpinBox()
        self.zip_q.setRange(30, 95)
        self.zip_q.setValue(70)
        self.zip_q.setFixedWidth(64)
        self.zip_q.setToolTip("JPEG 质量（越小体积越小）")
        zr.addWidget(self.zip_q)
        self.zip_row.setVisible(False)
        cb.addWidget(self.zip_row)

        self.fmt_box.currentIndexChanged.connect(self._sync_extra)
        self.zip_box.currentIndexChanged.connect(self._sync_extra)
        self.chk_num.toggled.connect(self.num_edit.setVisible)
        self.chk_wm.toggled.connect(self.wm_edit.setVisible)
        self.tile_box.currentIndexChanged.connect(
            lambda i: self.per_spin.setVisible(i > 0))
        self.chk_zip.toggled.connect(self._sync_extra)
        rv.addWidget(card1b)

        card2 = QFrame()
        card2.setObjectName("Card")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 14, 16, 16)
        c2.setSpacing(9)
        c2.addWidget(_section_label("输出位置"))

        c2.addWidget(QLabel("保存到"))
        drow = QHBoxLayout()
        drow.setSpacing(6)
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择输出文件夹")
        btn_dir = QPushButton("浏览")
        btn_dir.setObjectName("Ghost")
        btn_dir.clicked.connect(self._pick_dir)
        drow.addWidget(self.dir_edit, 1)
        drow.addWidget(btn_dir)
        c2.addLayout(drow)

        c2.addWidget(QLabel("文件名前缀"))
        self.prefix_edit = QLineEdit()
        self.prefix_edit.setPlaceholderText("例如 合同")
        c2.addWidget(self.prefix_edit)
        self.prefix_hint = QLabel("每页模式会自动加 _001、_002 …")
        self.prefix_hint.setObjectName("Faint")
        c2.addWidget(self.prefix_hint)

        self.chk_open = QCheckBox("完成后打开输出文件夹")
        self.chk_open.setChecked(True)
        c2.addWidget(self.chk_open)
        rv.addWidget(card2)

        rv.addWidget(hint_card("操作提示", [
            ("空格", "勾选 / 取消当前页"),
            ("Ctrl+A", "全选所有页"),
            ("Delete", "移除当前页"),
            ("拖动", "调整页面顺序"),
            ("Ctrl+Z", "撤销预览里的批注"),
        ]))

        rv.addStretch(1)

        self.run_btn = QPushButton("开始导出")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumHeight(46)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self._run)
        rv.addWidget(self.run_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        rv.addWidget(self.progress)

        self.status = QLabel("等待选择文件")
        self.status.setObjectName("Faint")
        self.status.setWordWrap(True)
        rv.addWidget(self.status)

        root.addWidget(side)

        # ---------------- 连接
        self.drop.clicked.connect(self._pick_file)
        self.drop.filesDropped.connect(self._on_drop)
        self.btn_pick.clicked.connect(self._pick_file)
        self.btn_all.clicked.connect(lambda: self.grid.set_all_checked(True))
        self.btn_inv.clicked.connect(self.grid.invert_checked)
        self.btn_none.clicked.connect(lambda: self.grid.set_all_checked(False))
        self.btn_rot.clicked.connect(self._rotate)
        self.btn_del.clicked.connect(self._delete_current)
        self.btn_zoom_s.clicked.connect(
            lambda: self.grid.set_thumb_size(self.grid.thumb_size() - 18))
        self.btn_zoom_l.clicked.connect(
            lambda: self.grid.set_thumb_size(self.grid.thumb_size() + 18))
        self.grid.selectionChanged.connect(self._on_selection)
        self.grid.currentChanged.connect(lambda _i: self._refresh_preview())
        self.grid.orderChanged.connect(self._refresh_preview)
        self.grid.requestToast.connect(lambda t: self.toast.emit(t, "info"))
        self.preview.inkAdded.connect(self._on_ink)
        self.preview.textAdded.connect(self._on_text)
        self.preview.undoRequested.connect(self._undo_note)
        self.preview.notesCleared.connect(self._clear_notes)

        QTimer.singleShot(0, self._resize_preview)
        QTimer.singleShot(0, self._sync_extra)

    # ------------------------------------------------------------------ 预览
    def _current_key(self) -> tuple[int, int] | None:
        item = self.grid.current_item()
        if item is None:
            return None
        return (item.src, item.index)

    def _refresh_preview(self) -> None:
        item = self.grid.current_item()
        if item is None or not self.sources:
            self.preview.clear()
            return
        key = (item.src, item.index)
        self.preview.show_ref(self.sources,
                              E.PageRef(item.src, item.index, item.rotation),
                              self.notes.get(key))

    # ------------------------------------------------------------------ 批注
    def _on_ink(self, points: list) -> None:
        key = self._current_key()
        if key is None:
            return
        color, width = self.preview.pen_style()
        note = annotate.InkStroke([(float(x), float(y)) for x, y in points],
                                  color, width)
        self.notes.setdefault(key, []).append(note)
        self._undo_stack.append((key, note))
        self.preview.refresh_notes(self.notes.get(key))

    def _on_text(self, x: float, y: float, text: str) -> None:
        key = self._current_key()
        if key is None:
            return
        color, font, size = self.preview.text_style()
        note = annotate.TextMark(x, y, text, color, font, size)
        self.notes.setdefault(key, []).append(note)
        self._undo_stack.append((key, note))
        self.preview.refresh_notes(self.notes.get(key))

    def _undo_note(self) -> None:
        if not self._undo_stack:
            self.toast.emit("没有可撤销的批注了", "info")
            return
        key, note = self._undo_stack.pop()
        bucket = self.notes.get(key)
        if bucket:
            for i in range(len(bucket) - 1, -1, -1):
                if bucket[i] is note:
                    bucket.pop(i)
                    break
            if not bucket:
                self.notes.pop(key, None)
        if self._current_key() == key:
            self.preview.refresh_notes(self.notes.get(key))

    def _clear_notes(self) -> None:
        key = self._current_key()
        if key is None:
            return
        if not self.notes.get(key):
            return
        self.notes.pop(key, None)
        self._undo_stack = [u for u in self._undo_stack if u[0] != key]
        self.preview.refresh_notes(None)
        self.toast.emit("已清空本页批注", "info")

    def _sync_extra(self) -> None:
        """按当前选择显示 / 隐藏附加选项，避免面板太长。"""
        is_img = self.fmt_box.currentIndex() > 0
        raster = self.chk_zip.isChecked() and self.zip_box.currentIndex() == 1
        self.dpi_spin.setVisible(is_img or raster)
        self.chk_zip.setVisible(not is_img)
        if is_img:
            self.chk_zip.setChecked(False)
        self.zip_row.setVisible(self.chk_zip.isChecked())
        if is_img:
            self.prefix_hint.setText("图片模式会自动加 _001、_002 …")
        else:
            self.prefix_hint.setText("每页模式会自动加 _001、_002 …")

    def _rotate(self) -> None:
        self.grid.rotate_current(90)
        self._refresh_preview()

    def _delete_current(self) -> None:
        key = self._current_key()
        if key is not None:
            self.notes.pop(key, None)
            self._undo_stack = [u for u in self._undo_stack if u[0] != key]
        self.grid.delete_current()
        self._refresh_preview()


    # -------------------------------------------------------------- 整区拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.toLocalFile()]
        if files:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self._on_drop(files)
        else:
            event.ignore()

    # ------------------------------------------------------------------ 文件
    def _pick_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "", FILTER)
        if paths:
            self.add_sources(paths)

    def _on_drop(self, files: list[str]) -> None:
        if not files:
            return
        self.add_sources(files)

    def _pick_dir(self) -> None:
        start = self.dir_edit.text().strip() or ""
        path = QFileDialog.getExistingDirectory(self, "选择输出文件夹", start)
        if path:
            self.dir_edit.setText(path)

    def add_sources(self, paths: list[str]) -> None:
        """导入一批 PDF / 图片，按顺序追加到页面池。"""
        existing = {os.path.normcase(s.path) for s in self.sources}
        added: list[E.Source] = []
        skipped = 0
        for p in paths:
            if os.path.normcase(p) in existing:
                skipped += 1
                continue
            try:
                src = E.make_source(p)
            except E.PdfError as exc:
                self.toast.emit(str(exc), "error")
                continue
            existing.add(os.path.normcase(p))
            added.append(src)

        if not added:
            if skipped:
                self.toast.emit("这些文件已经在列表里了", "info")
            return

        if self.grid.items:
            self.grid.append_sources(added)
            self.sources = list(self.grid.sources)
        else:
            self.grid.load(added)
            self.sources = list(self.grid.sources)
            self._apply_defaults()

        self.stack.setCurrentIndex(1)
        self._rebuild_chips()
        self._refresh_preview()
        self._refresh_state()

        pages = sum(s.page_count for s in added)
        msg = f"已导入 {len(added)} 个文件，共 {pages} 页"
        if skipped:
            msg += f"（{skipped} 个重复已跳过）"
        self.status.setText(f"{msg}，勾选后开始拆分")
        self.toast.emit(msg, "ok")

    def _apply_defaults(self) -> None:
        """按第一个来源文件给出默认的输出目录与文件名前缀。"""
        if not self.sources:
            return
        first = self.sources[0]
        base = first.stem
        self.prefix_edit.setText(base)
        self.dir_edit.setText(
            os.path.join(os.path.dirname(first.path), f"{base}_pages"))

    def _rebuild_chips(self) -> None:
        while self.chip_flow.count():
            item = self.chip_flow.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for i, src in enumerate(self.sources):
            chip = FileChip(i, src.name, src.kind)
            chip.removed.connect(self._remove_source)
            self.chip_flow.addWidget(chip)
        has = bool(self.sources)
        self.src_empty.setVisible(not has)
        self.chip_scroll.setVisible(has)
        self.src_count.setText(
            f"{len(self.sources)} 个文件 · {len(self.grid.items)} 页" if has
            else "0 个文件 · 0 页")
        self._relayout_chips()
        QTimer.singleShot(0, self._relayout_chips)

    def _relayout_chips(self) -> None:
        n = self.chip_flow.count()
        if not self.sources or n == 0:
            self.chip_host.setFixedHeight(0)
            self.chip_scroll.setFixedHeight(0)
            return
        # 预留滚动条宽度：这样滚动条出现/消失都不会让标签重新折行
        avail = self.chip_scroll.width() - 14
        if avail < 120:
            avail = 400
        row_w = 0
        rows = 1
        for i in range(n):
            w = self.chip_flow.itemAt(i).widget()
            if w is None:
                continue
            cw = max(w.sizeHint().width(), 60)
            if row_w and row_w + CHIP_GAP + cw > avail:
                rows += 1
                row_w = 0
            row_w += (CHIP_GAP if row_w else 0) + cw
        full = rows * CHIP_H + (rows - 1) * CHIP_GAP
        cap = CHIP_ROWS * CHIP_H + (CHIP_ROWS - 1) * CHIP_GAP
        self.chip_host.setFixedWidth(avail)
        self.chip_host.setFixedHeight(full)
        self.chip_scroll.setFixedHeight(min(full, cap))

    def _remove_source(self, index: int) -> None:
        if not (0 <= index < len(self.sources)):
            return
        name = self.sources[index].name
        self.grid.remove_source(index)
        self.sources = list(self.grid.sources)
        if not self.sources:
            self.stack.setCurrentIndex(0)
            self.status.setText("等待选择文件")
        self._rebuild_chips()
        self._refresh_preview()
        self._refresh_state()
        self.toast.emit(f"已移除《{name}》", "info")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout_chips()
        self._relayout_tools()
        self._resize_preview()

    def _resize_preview(self) -> None:
        """预览栏宽度可拖拽，但要夹在上下限内，不能把中间缩略图区挤没。"""
        total = self.split.width()
        if total < 240:
            return
        handle = self.split.handleWidth()
        cap = max(PREVIEW_MIN, min(PREVIEW_MAX, int(total * PREVIEW_RATIO)))
        cap = min(cap, max(PREVIEW_MIN, total - LEFT_MIN - handle))
        self.preview.setMaximumWidth(cap)

        sizes = self.split.sizes()
        if not sizes or len(sizes) < 2:
            return
        cur = sizes[0]
        if cur > cap:
            self.split.setSizes([cap, max(LEFT_MIN, total - cap - handle)])
        elif cur < PREVIEW_MIN:
            self.split.setSizes([PREVIEW_MIN, max(LEFT_MIN, total - PREVIEW_MIN - handle)])

    def _relayout_tools(self) -> None:
        """工具行用 FlowLayout 自动换行，需要手动把高度撑到实际行数。"""
        w = self.tools.width()
        if w < 80:
            return
        h = self.tools.layout().heightForWidth(w)
        if h > 0 and h != self.tools.height():
            self.tools.setFixedHeight(h)

    def _on_selection(self) -> None:
        self._refresh_state()

    def _refresh_state(self) -> None:
        total = len(self.grid.items)
        checked = self.grid.checked_count()
        self.count_label.setText(f"已选 {checked} / {total} 页")
        has_file = bool(self.sources) and total > 0
        busy = self._worker is not None and self._worker.isRunning()
        self.run_btn.setEnabled(has_file and checked > 0 and not busy)
        for b in (self.btn_all, self.btn_inv, self.btn_none, self.btn_rot,
                  self.btn_del, self.btn_zoom_s, self.btn_zoom_l):
            b.setEnabled(has_file and not busy)

    # ------------------------------------------------------------------ 执行
    def _run(self) -> None:
        if not self.sources:
            self.toast.emit("先导入 PDF 或图片", "error")
            return
        refs = self.grid.selected_refs()
        if not refs:
            self.toast.emit("还没有勾选任何页面", "error")
            return
        out_dir = self.dir_edit.text().strip()
        if not out_dir:
            self.toast.emit("请选择输出文件夹", "error")
            return
        prefix = self.prefix_edit.text().strip() or "output"
        mode = ["each", "single", "every_n"][self.mode_group.current_index()]
        fmt = ["pdf", "png", "jpg"][self.fmt_box.currentIndex()]
        tile = ["none", "h", "v"][self.tile_box.currentIndex()]
        marks = E.Marks(
            page_numbers=self.chk_num.isChecked(),
            number_format=self.num_edit.text().strip() or "{n} / {total}",
            watermark=self.wm_edit.text().strip() if self.chk_wm.isChecked() else "",
        )
        compress = None
        if self.chk_zip.isChecked() and fmt == "pdf":
            compress = ("raster" if self.zip_box.currentIndex() == 1 else "lossless",
                        self.dpi_spin.value(), self.zip_q.value())

        self._set_busy(True)
        self.progress.setValue(0)
        self.status.setText("准备中…")
        self._worker = _SplitWorker(self.sources, refs, mode, out_dir, prefix,
                                    self.n_spin.value(), fmt=fmt,
                                    dpi=self.dpi_spin.value(),
                                    quality=self.zip_q.value(), marks=marks,
                                    notes=dict(self.notes), tile=tile,
                                    per_page=self.per_spin.value(),
                                    compress=compress)
        self._worker.progress.connect(self._on_progress)
        self._worker.ok.connect(self._on_ok)
        self._worker.err.connect(self._on_err)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.setText("正在导出…" if busy else "开始导出")
        self._refresh_state()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.status.setText(msg)

    def _on_ok(self, files: list[str]) -> None:
        self._last_out = os.path.dirname(files[0]) if files else ""
        self.progress.setValue(100)
        self.status.setText(f"完成：生成 {len(files)} 个文件 → {self._last_out}")
        self.toast.emit(f"拆分完成，共生成 {len(files)} 个文件", "ok")
        if self.chk_open.isChecked() and self._last_out:
            try:
                os.startfile(self._last_out)  # noqa: S606
            except OSError:
                pass

    def _on_err(self, msg: str) -> None:
        self.status.setText("出错了")
        self.toast.emit(msg, "error")

    def _on_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._set_busy(False)
