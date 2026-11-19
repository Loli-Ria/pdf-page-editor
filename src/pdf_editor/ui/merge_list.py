# -*- coding: utf-8 -*-
"""合并页的文件列表：自绘、可拖拽排序。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from PySide6.QtCore import (QObject, QPoint, QPointF, QRect, QRectF, QRunnable,
                            QSize, Qt, QThreadPool, Signal)
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QScrollArea, QWidget

from ..core import engine as E
from . import theme


@dataclass
class MergeEntry:
    path: str
    kind: str                 # "pdf" | "image"
    label: str = ""
    meta: str = ""
    pixmap: QPixmap | None = None
    token: int = 0
    error: str = ""


class _Sig(QObject):
    done = Signal(int, int, bytes)   # generation, token, png


class _Task(QRunnable):
    def __init__(self, sig: _Sig, gen: int, token: int, entry: MergeEntry) -> None:
        super().__init__()
        self.sig = sig
        self.gen = gen
        self.token = token
        self.entry = entry

    def run(self) -> None:
        try:
            if self.entry.kind == "pdf":
                data = E.render_page_png(self.entry.path, 0, max_side=260)
            else:
                data = E.render_image_thumb(self.entry.path, 200)
        except Exception:  # noqa: BLE001
            data = b""
        try:
            self.sig.done.emit(self.gen, self.token, data)
        except RuntimeError:
            pass


class MergeList(QWidget):
    selectionChanged = Signal()
    orderChanged = Signal()

    MARGIN = 4
    ROW_H = 70
    GAP = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.entries: list[MergeEntry] = []
        self.current = -1
        self._hover = -1
        self._press: QPoint | None = None
        self._maybe_drag: int | None = None
        self._drag_from: int | None = None
        self._drop_index: int | None = None
        self._scroll: QScrollArea | None = None

        self._gen = 0
        self._token = 0
        self._sig = _Sig()
        self._sig.done.connect(self._on_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)

    # -------------------------------------------------------------- 数据
    def set_scroll_area(self, area: QScrollArea) -> None:
        self._scroll = area

    def add_paths(self, paths: list[str]) -> int:
        added = 0
        for p in paths:
            kind = E.kind_of(p)
            if kind is None:
                continue
            entry = MergeEntry(path=p, kind=kind, label=os.path.basename(p))
            try:
                if kind == "pdf":
                    n = E.pdf_page_count(p)
                    size = E.human_size(os.path.getsize(p))
                    entry.meta = f"PDF · {n} 页 · {size}"
                else:
                    w, h = E.image_info(p)
                    entry.meta = f"图片 · {w}×{h}"
            except Exception as exc:  # noqa: BLE001
                entry.meta = "读取失败"
                entry.error = str(exc)
            self.entries.append(entry)
            added += 1
        if added:
            self._update_geometry()
            self._request_all()
            if self.current < 0:
                self.current = 0
            self.selectionChanged.emit()
            self.update()
        return added

    def clear(self) -> None:
        self._gen += 1
        self.entries = []
        self.current = -1
        self._update_geometry()
        self.selectionChanged.emit()
        self.update()

    def remove_current(self) -> None:
        if 0 <= self.current < len(self.entries):
            self.entries.pop(self.current)
            self.current = min(self.current, len(self.entries) - 1)
            self._update_geometry()
            self.orderChanged.emit()
            self.selectionChanged.emit()
            self.update()

    def move_current(self, delta: int) -> None:
        i = self.current
        j = i + delta
        if 0 <= i < len(self.entries) and 0 <= j < len(self.entries):
            self.entries[i], self.entries[j] = self.entries[j], self.entries[i]
            self.current = j
            self.orderChanged.emit()
            self.update()

    # -------------------------------------------------------------- 缩略图
    def _request_all(self) -> None:
        for e in self.entries:
            self._token += 1
            e.token = self._token
            self._pool.start(_Task(self._sig, self._gen, e.token, e))

    def _on_ready(self, gen: int, token: int, data: bytes) -> None:
        if gen != self._gen or not data:
            return
        img = QImage()
        if not img.loadFromData(data):
            return
        pm = QPixmap.fromImage(img)
        for e in self.entries:
            if e.token == token:
                e.pixmap = pm
                self.update()
                return

    # -------------------------------------------------------------- 几何
    def _row_rect(self, i: int) -> QRect:
        return QRect(self.MARGIN, self.MARGIN + i * (self.ROW_H + self.GAP),
                     max(1, self.width() - 2 * self.MARGIN), self.ROW_H)

    def _update_geometry(self) -> None:
        n = len(self.entries)
        h = self.MARGIN * 2 + n * self.ROW_H + max(0, n - 1) * self.GAP
        self.setMinimumHeight(h)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(560, max(120, self.minimumHeight()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._update_geometry()
        super().resizeEvent(event)

    def _index_at(self, pos: QPoint) -> int:
        for i in range(len(self.entries)):
            if self._row_rect(i).contains(pos):
                return i
        return -1

    # -------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for i, e in enumerate(self.entries):
            self._paint_row(p, i, e)
        if self._drag_from is not None and self._drop_index is not None:
            n = len(self.entries)
            idx = min(max(self._drop_index, 0), n)
            if idx < n:
                y = self._row_rect(idx).top() - self.GAP / 2
            elif n:
                y = self._row_rect(n - 1).bottom() + self.GAP / 2
            else:
                y = self.MARGIN
            p.setPen(QPen(QColor(theme.ACCENT), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(self.MARGIN + 8, y), QPointF(self.width() - self.MARGIN - 8, y))

    def _paint_row(self, p: QPainter, i: int, e: MergeEntry) -> None:
        r = QRectF(self._row_rect(i)).adjusted(0.5, 0.5, -0.5, -0.5)
        selected = (i == self.current)
        hover = (i == self._hover)
        p.setOpacity(0.35 if self._drag_from == i else 1.0)
        if selected:
            bg = QColor(theme.ACCENT_SOFT)
        elif hover:
            bg = QColor("#F7F9FD")
        else:
            bg = QColor(theme.SURFACE)
        p.setBrush(bg)
        p.setPen(QPen(QColor(theme.ACCENT if selected else theme.BORDER),
                      1.4 if selected else 1.0))
        p.drawRoundedRect(r, 10, 10)

        # 序号
        p.setPen(QColor(theme.TEXT_FAINT))
        f = QFont()
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(QRectF(r.x() + 6, r.y(), 24, r.height()), Qt.AlignCenter, str(i + 1))

        # 缩略图
        tw, th = 38, 50
        tr = QRectF(r.x() + 34, r.y() + (r.height() - th) / 2, tw, th)
        if e.pixmap is not None and not e.pixmap.isNull():
            scaled = e.pixmap.scaled(QSize(tw, th), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(int(tr.x() + (tw - scaled.width()) / 2),
                         int(tr.y() + (th - scaled.height()) / 2), scaled)
            p.setPen(QPen(QColor("#DCE2EC"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRect(int(tr.x() + (tw - scaled.width()) / 2),
                             int(tr.y() + (th - scaled.height()) / 2),
                             scaled.width(), scaled.height()))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#EDF0F6"))
            p.drawRoundedRect(tr, 5, 5)
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(tr, Qt.AlignCenter, "…")

        # 文本
        text_x = r.x() + 84
        text_w = r.width() - 100
        p.setPen(QColor(theme.TEXT))
        f2 = QFont()
        f2.setPixelSize(13)
        f2.setBold(True)
        p.setFont(f2)
        fm = p.fontMetrics()
        name = fm.elidedText(e.label, Qt.ElideMiddle, int(text_w))
        p.drawText(QRectF(text_x, r.y() + 15, text_w, 20), Qt.AlignVCenter, name)

        p.setPen(QColor(theme.DANGER if e.error else theme.TEXT_MUTED))
        f3 = QFont()
        f3.setPixelSize(11)
        p.setFont(f3)
        meta = e.error if e.error else e.meta
        p.drawText(QRectF(text_x, r.y() + 37, text_w, 18), Qt.AlignVCenter,
                   p.fontMetrics().elidedText(meta, Qt.ElideRight, int(text_w)))
        p.setOpacity(1.0)

    # -------------------------------------------------------------- 事件
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            i = self._index_at(pos)
            if i >= 0:
                self.current = i
                self._press = pos
                self._maybe_drag = i
                self._drag_from = None
                self._drop_index = None
                self.setFocus()
                self.selectionChanged.emit()
                self.update()
            else:
                self.current = -1
                self.selectionChanged.emit()
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._maybe_drag is not None and (event.buttons() & Qt.LeftButton):
            if self._press is not None and (pos - self._press).manhattanLength() > 6:
                self._drag_from = self._maybe_drag
                self._maybe_drag = None
        if self._drag_from is not None:
            self._drop_index = self._drop_index_at(pos)
            self._auto_scroll(pos)
            self.update()
        else:
            h = self._index_at(pos)
            if h != self._hover:
                self._hover = h
                self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and self._drop_index is not None:
            frm = self._drag_from
            to = self._drop_index
            if to > frm:
                to -= 1
            if 0 <= to < len(self.entries) and to != frm:
                e = self.entries.pop(frm)
                self.entries.insert(to, e)
                self.current = to
                self.orderChanged.emit()
                self.selectionChanged.emit()
        self._drag_from = None
        self._maybe_drag = None
        self._drop_index = None
        self._press = None
        self.update()
        super().mouseReleaseEvent(event)

    def _auto_scroll(self, pos: QPoint) -> None:
        if self._scroll is None:
            return
        bar = self._scroll.verticalScrollBar()
        vp_y = self.mapTo(self._scroll.viewport(), pos).y()
        if vp_y < 40:
            bar.setValue(bar.value() - 18)
        elif vp_y > self._scroll.viewport().height() - 40:
            bar.setValue(bar.value() + 18)

    def _drop_index_at(self, pos: QPoint) -> int:
        n = len(self.entries)
        for i in range(n):
            if pos.y() < self._row_rect(i).center().y():
                return i
        return n

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_current()
            return
        if key == Qt.Key_Up and self.current > 0:
            self.current -= 1
            self.selectionChanged.emit()
            self.update()
            return
        if key == Qt.Key_Down and self.current < len(self.entries) - 1:
            self.current += 1
            self.selectionChanged.emit()
            self.update()
            return
        super().keyPressEvent(event)
