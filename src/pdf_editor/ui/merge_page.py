# -*- coding: utf-8 -*-
"""合并页：多个 PDF + 图片 → 一个 PDF。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QProgressBar, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core import engine as E
from . import theme
from .widgets import DropZone, RadioCardGroup, SidePanel, hint_card
from .merge_list import MergeList


class _MergeWorker(QThread):
    progress = Signal(int, str)
    ok = Signal(str)
    err = Signal(str)

    def __init__(self, items, out_path: str, image_mode: str, dpi: int) -> None:
        super().__init__()
        self.items = items
        self.out_path = out_path
        self.image_mode = image_mode
        self.dpi = dpi

    def run(self) -> None:
        try:
            path = E.merge_to_pdf(self.items, self.out_path, self.image_mode,
                                  self.dpi, self.progress.emit)
            self.ok.emit(path)
        except Exception as exc:  # noqa: BLE001
            self.err.emit(str(exc))


def _section_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("SectionTitle")
    return lab


FILTER = "PDF 和图片 (*.pdf *.jpg *.jpeg *.png *.bmp *.webp *.tif *.tiff *.gif)"


class MergePage(QWidget):
    toast = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _MergeWorker | None = None
        self.setAcceptDrops(True)
        self._build()
        self._refresh_state()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(12)

        self.drop = DropZone("把 PDF 或图片拖到这里",
                             "支持 PDF / JPG / PNG / BMP / WEBP / TIFF，可一次拖入多个")
        self.drop.setMinimumHeight(92)
        self.drop.clicked.connect(self._pick_files)
        self.drop.filesDropped.connect(self._add_paths)
        left.addWidget(self.drop)

        tools = QWidget()
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(2, 0, 2, 0)
        tl.setSpacing(8)

        def ghost(text: str, tip: str = "") -> QPushButton:
            b = QPushButton(text)
            b.setObjectName("Ghost")
            b.setCursor(Qt.PointingHandCursor)
            if tip:
                b.setToolTip(tip)
            return b

        self.btn_add = ghost("添加文件")
        self.btn_up = ghost("上移")
        self.btn_down = ghost("下移")
        self.btn_del = ghost("移除")
        self.btn_clear = ghost("清空")
        self.count_label = QLabel("共 0 个文件 · 0 页")
        self.count_label.setObjectName("Hint")

        tl.addWidget(self.btn_add)
        tl.addSpacing(8)
        tl.addWidget(self.btn_up)
        tl.addWidget(self.btn_down)
        tl.addWidget(self.btn_del)
        tl.addWidget(self.btn_clear)
        tl.addStretch(1)
        tl.addWidget(self.count_label)
        left.addWidget(tools)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = MergeList()
        self.list.set_scroll_area(self.scroll)
        self.scroll.setWidget(self.list)

        self.empty = QWidget()
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.addStretch(1)
        hint = QLabel("还没有文件 · 拖入或点击上方区域添加")
        hint.setObjectName("Faint")
        hint.setAlignment(Qt.AlignCenter)
        ev.addWidget(hint)
        ev.addStretch(1)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.scroll)
        left.addWidget(self.stack, 1)
        root.addLayout(left, 1)

        # ---------------- 右侧
        side = SidePanel(344)
        rv = side.v

        card1 = QFrame()
        card1.setObjectName("Card")
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(16, 14, 16, 16)
        c1.setSpacing(10)
        c1.addWidget(_section_label("图片页面"))
        self.mode_group = RadioCardGroup()
        self.mode_group.add_card("统一 A4", "图片等比缩放、居中放进 A4 白底页")
        self.mode_group.add_card("保持原尺寸", "页面大小跟随图片本身")
        c1.addWidget(self.mode_group)

        self.dpi_row = QWidget()
        dr = QHBoxLayout(self.dpi_row)
        dr.setContentsMargins(2, 0, 2, 0)
        dr.setSpacing(8)
        dr.addWidget(QLabel("按"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(36, 1200)
        self.dpi_spin.setValue(200)
        self.dpi_spin.setFixedWidth(84)
        dr.addWidget(self.dpi_spin)
        dr.addWidget(QLabel("DPI 换算物理尺寸"))
        dr.addStretch(1)
        c1.addWidget(self.dpi_row)
        self.dpi_row.setVisible(False)
        self.mode_group.changed.connect(lambda i: self.dpi_row.setVisible(i == 1))
        rv.addWidget(card1)

        card2 = QFrame()
        card2.setObjectName("Card")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 14, 16, 16)
        c2.setSpacing(9)
        c2.addWidget(_section_label("输出文件"))
        c2.addWidget(QLabel("保存为"))
        orow = QHBoxLayout()
        orow.setSpacing(6)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("例如 D:\\输出\\合并结果.pdf")
        btn_browse = QPushButton("浏览")
        btn_browse.setObjectName("Ghost")
        btn_browse.clicked.connect(self._pick_out)
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(btn_browse)
        c2.addLayout(orow)
        self.chk_open = QCheckBox("完成后打开所在文件夹")
        self.chk_open.setChecked(True)
        c2.addWidget(self.chk_open)
        rv.addWidget(card2)

        rv.addWidget(hint_card("操作提示", [
            ("拖动", "调整文件顺序"),
            ("↑ ↓", "上移 / 下移选中项"),
            ("Delete", "移除选中文件"),
        ]))

        rv.addStretch(1)

        self.run_btn = QPushButton("开始合并")
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

        self.status = QLabel("等待添加文件")
        self.status.setObjectName("Faint")
        self.status.setWordWrap(True)
        rv.addWidget(self.status)

        root.addWidget(side)

        # ---------------- 连接
        self.btn_add.clicked.connect(self._pick_files)
        self.btn_up.clicked.connect(lambda: self.list.move_current(-1))
        self.btn_down.clicked.connect(lambda: self.list.move_current(1))
        self.btn_del.clicked.connect(self.list.remove_current)
        self.btn_clear.clicked.connect(self._clear)
        self.list.selectionChanged.connect(self._refresh_state)
        self.list.orderChanged.connect(self._refresh_state)

    # ------------------------------------------------------------------ 文件

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
            self._add_paths(files)
        else:
            event.ignore()

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择 PDF 或图片", "", FILTER)
        if paths:
            self._add_paths(paths)

    def _add_paths(self, paths: list[str]) -> None:
        supported = [p for p in paths if E.kind_of(p)]
        skipped = len(paths) - len(supported)
        if not supported:
            self.toast.emit("这些文件类型不支持", "error")
            return
        n = self.list.add_paths(supported)
        if not self.out_edit.text().strip() and self.list.entries:
            first = os.path.dirname(self.list.entries[0].path)
            self.out_edit.setText(os.path.join(first, "合并结果.pdf"))
        self._refresh_state()
        msg = f"已添加 {n} 个文件"
        if skipped:
            msg += f"，跳过 {skipped} 个不支持的文件"
        self.toast.emit(msg, "ok" if not skipped else "info")

    def _clear(self) -> None:
        self.list.clear()
        self._refresh_state()

    def _pick_out(self) -> None:
        start = self.out_edit.text().strip() or ""
        path, _ = QFileDialog.getSaveFileName(self, "保存合并结果", start,
                                              "PDF 文件 (*.pdf)")
        if path:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.out_edit.setText(path)

    def _refresh_state(self) -> None:
        entries = self.list.entries
        total = len(entries)
        self.stack.setCurrentIndex(1 if total else 0)
        self.count_label.setText(f"共 {total} 个文件 · {E.estimate_pages([E.MergeItem(e.path, e.kind) for e in entries])} 页")
        busy = self._worker is not None and self._worker.isRunning()
        self.run_btn.setEnabled(total > 0 and not busy)
        for b in (self.btn_add, self.btn_up, self.btn_down, self.btn_del, self.btn_clear):
            b.setEnabled(not busy)
        self.btn_up.setEnabled(not busy and self.list.current > 0)
        self.btn_down.setEnabled(not busy and 0 <= self.list.current < total - 1)
        self.btn_del.setEnabled(not busy and 0 <= self.list.current < total)

    # ------------------------------------------------------------------ 执行
    def _run(self) -> None:
        entries = self.list.entries
        if not entries:
            self.toast.emit("先添加文件", "error")
            return
        out_path = self.out_edit.text().strip()
        if not out_path:
            self.toast.emit("请指定输出文件路径", "error")
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"
            self.out_edit.setText(out_path)
        bad = [e for e in entries if e.error]
        if bad:
            self.toast.emit(f"有 {len(bad)} 个文件读取失败，请先移除它们", "error")
            return

        items = [E.MergeItem(e.path, e.kind) for e in entries]
        image_mode = "a4" if self.mode_group.current_index() == 0 else "original"

        self._set_busy(True)
        self.progress.setValue(0)
        self.status.setText("准备中…")
        self._worker = _MergeWorker(items, out_path, image_mode, self.dpi_spin.value())
        self._worker.progress.connect(self._on_progress)
        self._worker.ok.connect(self._on_ok)
        self._worker.err.connect(self._on_err)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        self.run_btn.setText("正在合并…" if busy else "开始合并")
        self._refresh_state()

    def _on_progress(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.status.setText(msg)

    def _on_ok(self, path: str) -> None:
        self.progress.setValue(100)
        self.status.setText(f"完成：{path}")
        self.toast.emit(f"合并完成：{os.path.basename(path)}", "ok")
        if self.chk_open.isChecked():
            try:
                os.startfile(os.path.dirname(path))  # noqa: S606
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
