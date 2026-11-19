# -*- coding: utf-8 -*-
"""缩略图网格：自定义绘制 + 勾选 + 拖拽重排 + 旋转/删除。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import (QObject, QPoint, QPointF, QRect, QRectF, QRunnable,
                            QSize, Qt, QThreadPool, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QImage, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import QMenu, QScrollArea, QWidget

from . import theme
from ..core.engine import PageRef, Source, render_ref_png


@dataclass
class PageItem:
    src: int = 0               # 来源文件序号
    index: int = 0             # 源文件内页码（0 基）
    rotation: int = 0          # 附加旋转
    checked: bool = True
    pixmap: QPixmap | None = None
    token: int = 0             # 缩略图请求号，用于丢弃过期结果


class _ThumbSignals(QObject):
    done = Signal(int, int, bytes)  # generation, token, png


class _ThumbTask(QRunnable):
    def __init__(self, signals: _ThumbSignals, generation: int, token: int,
                 sources: list[Source], ref: PageRef, max_side: int) -> None:
        super().__init__()
        self.signals = signals
        self.generation = generation
        self.token = token
        self.sources = sources
        self.ref = ref
        self.max_side = max_side

    def run(self) -> None:
        try:
            data = render_ref_png(self.sources, self.ref, self.max_side)
        except Exception:  # noqa: BLE001
            data = b""
        try:
            self.signals.done.emit(self.generation, self.token, data)
        except RuntimeError:
            pass


class PageGrid(QWidget):
    """网格化的页面缩略图。所有数据都在 Python 侧，控件只负责画和收事件。"""

    selectionChanged = Signal()      # 勾选集合变化
    orderChanged = Signal()
    currentChanged = Signal(int)
    requestToast = Signal(str)

    MARGIN = 18
    GAP = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(False)
        self.items: list[PageItem] = []
        self.current = -1
        self.sources: list[Source] = []
        self.cell_w = 132
        self.cell_h = 176
        self._thumb_side = 340

        self._press_pos: QPoint | None = None
        self._maybe_drag: int | None = None
        self._drag_from: int | None = None
        self._drop_index: int | None = None
        self._scroll: QScrollArea | None = None

        self._gen = 0
        self._token = 0
        self._signals = _ThumbSignals()
        self._signals.done.connect(self._on_thumb_ready)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, (QThreadPool.globalInstance().maxThreadCount() or 4) // 2))

    # ------------------------------------------------------------------ 数据
    def set_scroll_area(self, area: QScrollArea) -> None:
        self._scroll = area

    def load(self, sources: list[Source]) -> None:
        """按来源列表重建整个网格（来源顺序 = 页面顺序）。"""
        self.clear()
        self.sources = list(sources)
        self.items = []
        for si, src in enumerate(self.sources):
            for pi in range(src.page_count):
                self.items.append(PageItem(si, pi))
        self.current = 0 if self.items else -1
        self._update_geometry()
        self._request_all_thumbs()
        self.selectionChanged.emit()
        self.update()

    def append_sources(self, sources: list[Source]) -> None:
        """在末尾追加来源，保留已有的勾选 / 旋转 / 顺序。"""
        base = len(self.sources)
        self.sources.extend(sources)
        for k, src in enumerate(sources):
            for pi in range(src.page_count):
                self.items.append(PageItem(base + k, pi))
        self._update_geometry()
        for i in range(len(self.items) - sum(s.page_count for s in sources),
                       len(self.items)):
            self._request_thumb(i)
        self.selectionChanged.emit()
        self.update()

    def remove_source(self, src_index: int) -> None:
        """移除某个来源文件及其全部页面，并重排其余来源序号。"""
        if not (0 <= src_index < len(self.sources)):
            return
        self.sources.pop(src_index)
        kept = []
        for it in self.items:
            if it.src == src_index:
                continue
            if it.src > src_index:
                it.src -= 1
            kept.append(it)
        self.items = kept
        self.current = min(self.current, len(self.items) - 1) if self.items else -1
        self._update_geometry()
        self.orderChanged.emit()
        self.selectionChanged.emit()
        self.update()

    def clear(self) -> None:
        self._gen += 1
        self.items = []
        self.current = -1
        self.sources = []
        self._update_geometry()
        self.update()

    def all_checked(self) -> bool:
        return bool(self.items) and all(it.checked for it in self.items)

    def checked_count(self) -> int:
        return sum(1 for it in self.items if it.checked)

    def selected_refs(self) -> list[PageRef]:
        return [PageRef(it.src, it.index, it.rotation)
                for it in self.items if it.checked]

    def all_refs(self) -> list[PageRef]:
        return [PageRef(it.src, it.index, it.rotation) for it in self.items]

    def checked_source_pages(self) -> list[int]:
        return [it.index for it in self.items if it.checked]

    # ------------------------------------------------------------------ 操作
    def set_all_checked(self, value: bool) -> None:
        for it in self.items:
            it.checked = value
        self.selectionChanged.emit()
        self.update()

    def invert_checked(self) -> None:
        for it in self.items:
            it.checked = not it.checked
        self.selectionChanged.emit()
        self.update()

    def current_item(self) -> PageItem | None:
        if 0 <= self.current < len(self.items):
            return self.items[self.current]
        return None

    def rotate_current(self, delta: int) -> None:
        if 0 <= self.current < len(self.items):
            it = self.items[self.current]
            it.rotation = (it.rotation + delta) % 360
            self._request_thumb(self.current)
            self.update()
            self.requestToast.emit(f"第 {it.index + 1} 页已旋转 {it.rotation}°")

    def delete_current(self) -> None:
        if 0 <= self.current < len(self.items):
            it = self.items.pop(self.current)
            if self.items:
                self.current = min(self.current, len(self.items) - 1)
            else:
                self.current = -1
            self._update_geometry()
            self.orderChanged.emit()
            self.selectionChanged.emit()
            self.update()
            self.requestToast.emit(f"已移除第 {it.index + 1} 页")

    def delete_unchecked(self) -> None:
        n = sum(1 for it in self.items if not it.checked)
        self.items = [it for it in self.items if it.checked]
        self.current = min(self.current, len(self.items) - 1) if self.items else -1
        self._update_geometry()
        self.orderChanged.emit()
        self.selectionChanged.emit()
        self.update()
        if n:
            self.requestToast.emit(f"已移除 {n} 页未勾选的页面")

    def set_thumb_size(self, px: int) -> None:
        px = max(88, min(230, px))
        if px == self.cell_w:
            return
        self.cell_w = px
        self.cell_h = int(px * 1.33) + 26
        self._thumb_side = int(px * 2.6)
        self._update_geometry()
        self._request_all_thumbs()
        self.update()

    def thumb_size(self) -> int:
        return self.cell_w

    # ------------------------------------------------------------- 缩略图加载
    def _request_all_thumbs(self) -> None:
        for i in range(len(self.items)):
            self._request_thumb(i)

    def _request_thumb(self, i: int) -> None:
        if not (0 <= i < len(self.items)) or not self.sources:
            return
        it = self.items[i]
        if not (0 <= it.src < len(self.sources)):
            return
        self._token += 1
        it.token = self._token
        task = _ThumbTask(self._signals, self._gen, self._token, self.sources,
                          PageRef(it.src, it.index, it.rotation), self._thumb_side)
        self._pool.start(task)

    def _on_thumb_ready(self, generation: int, token: int, data: bytes) -> None:
        if generation != self._gen or not data:
            return
        img = QImage()
        if not img.loadFromData(data):
            return
        pm = QPixmap.fromImage(img)
        for it in self.items:
            if it.token == token:
                it.pixmap = pm
                self.update()
                return

    # ------------------------------------------------------------------ 布局
    def _cols(self) -> int:
        avail = max(1, self.width() - 2 * self.MARGIN)
        return max(1, int((avail + self.GAP) // (self.cell_w + self.GAP)))

    def _cell_rect(self, i: int) -> QRect:
        cols = self._cols()
        row, col = divmod(i, cols)
        x = self.MARGIN + col * (self.cell_w + self.GAP)
        y = self.MARGIN + row * (self.cell_h + self.GAP)
        return QRect(x, y, self.cell_w, self.cell_h)

    def _update_geometry(self) -> None:
        cols = self._cols()
        rows = max(1, math.ceil(len(self.items) / cols)) if self.items else 1
        h = self.MARGIN * 2 + rows * self.cell_h + max(0, rows - 1) * self.GAP
        self.setMinimumHeight(h if self.items else 0)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(600, max(200, self.minimumHeight()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._update_geometry()
        super().resizeEvent(event)

    def _index_at(self, pos: QPoint) -> int:
        for i in range(len(self.items)):
            if self._cell_rect(i).contains(pos):
                return i
        return -1

    def _check_rect(self, cell: QRect) -> QRectF:
        return QRectF(cell.x() + 6, cell.y() + 6, 18, 18)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for i, item in enumerate(self.items):
            self._paint_cell(p, i, item)
        if self._drag_from is not None and self._drop_index is not None:
            self._paint_drop_line(p)

    def _paint_cell(self, p: QPainter, i: int, item: PageItem) -> None:
        cell = self._cell_rect(i)
        r = QRectF(cell).adjusted(0.5, 0.5, -0.5, -0.5)
        selected = (i == self.current)
        dragging = (self._drag_from == i)

        p.setOpacity(0.35 if dragging else 1.0)
        p.setBrush(QColor(theme.ACCENT_SOFT if selected else theme.SURFACE))
        pen = QPen(QColor(theme.ACCENT if selected else theme.BORDER), 1.6 if selected else 1.0)
        p.setPen(pen)
        p.drawRoundedRect(r, 11, 11)

        thumb = QRectF(r.x() + 8, r.y() + 8, r.width() - 16, r.height() - 38)
        if item.pixmap is not None and not item.pixmap.isNull():
            scaled = item.pixmap.scaled(thumb.size().toSize(), Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation)
            x = thumb.x() + (thumb.width() - scaled.width()) / 2
            y = thumb.y() + (thumb.height() - scaled.height()) / 2
            p.drawPixmap(int(x), int(y), scaled)
            p.setPen(QPen(QColor("#DCE2EC"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRect(int(x), int(y), scaled.width(), scaled.height()))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#EDF0F6"))
            p.drawRoundedRect(thumb, 7, 7)
            p.setPen(QColor(theme.TEXT_FAINT))
            f = QFont()
            f.setPixelSize(16)
            p.setFont(f)
            p.drawText(thumb, Qt.AlignCenter, "…")

        # 页码
        p.setPen(QColor(theme.TEXT if selected else theme.TEXT_MUTED))
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        label = str(item.index + 1)
        if len(self.sources) > 1:
            label = f"{item.src + 1}-{item.index + 1}"
        if item.rotation:
            label += f"   ↻{item.rotation}°"
        p.drawText(QRectF(r.x(), r.bottom() - 27, r.width(), 22), Qt.AlignCenter, label)

        # 勾选圈
        cc = self._check_rect(cell)
        if item.checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(cc)
            p.setPen(QPen(QColor("#FFFFFF"), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(QPointF(cc.x() + 4.6, cc.center().y() + 0.4))
            path.lineTo(cc.x() + 7.6, cc.center().y() + 3.4)
            path.lineTo(cc.x() + 13.2, cc.center().y() - 3.6)
            p.drawPath(path)
        else:
            p.setPen(QPen(QColor(theme.BORDER_STRONG), 1.4))
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawEllipse(cc)
        p.setOpacity(1.0)

    def _paint_drop_line(self, p: QPainter) -> None:
        n = len(self.items)
        idx = min(max(self._drop_index or 0, 0), n)
        if idx < n:
            cell = self._cell_rect(idx)
            x = cell.x() - self.GAP / 2
            y0, y1 = cell.y(), cell.y() + cell.height()
        elif n:
            cell = self._cell_rect(n - 1)
            x = cell.right() + self.GAP / 2
            y0, y1 = cell.y(), cell.y() + cell.height()
        else:
            return
        p.setPen(QPen(QColor(theme.ACCENT), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x, y0 + 2), QPointF(x, y1 - 2))

    # ------------------------------------------------------------------ 鼠标
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            pos = event.position().toPoint()
            i = self._index_at(pos)
            if i >= 0:
                if self._check_rect(self._cell_rect(i)).adjusted(-4, -4, 4, 4).contains(event.position()):
                    self.items[i].checked = not self.items[i].checked
                    self.selectionChanged.emit()
                    self.update()
                    return
                self.current = i
                self._press_pos = pos
                self._maybe_drag = i
                self._drag_from = None
                self._drop_index = None
                self.setFocus()
                self.update()
                self.currentChanged.emit(i)
            else:
                self.current = -1
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._maybe_drag is not None and (event.buttons() & Qt.LeftButton):
            if self._press_pos is not None and (pos - self._press_pos).manhattanLength() > 8:
                self._drag_from = self._maybe_drag
                self._maybe_drag = None
        if self._drag_from is not None:
            self._drop_index = self._drop_index_at(pos)
            self._auto_scroll(pos)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_from is not None and self._drop_index is not None:
            frm = self._drag_from
            to = self._drop_index
            if to > frm:
                to -= 1
            if 0 <= to < len(self.items) and to != frm:
                item = self.items.pop(frm)
                self.items.insert(to, item)
                self.current = to
                self.orderChanged.emit()
                self.currentChanged.emit(to)
        self._drag_from = None
        self._maybe_drag = None
        self._drop_index = None
        self._press_pos = None
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
        n = len(self.items)
        if n == 0:
            return 0
        if pos.y() > self._cell_rect(n - 1).bottom():
            return n
        best_i, best_d = 0, None
        for i in range(n):
            r = self._cell_rect(i)
            d = abs(pos.x() - r.center().x()) + abs(pos.y() - r.center().y()) * 2
            if best_d is None or d < best_d:
                best_d, best_i = d, i
        r = self._cell_rect(best_i)
        return best_i if pos.x() < r.center().x() else best_i + 1

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key_Space and 0 <= self.current < len(self.items):
            self.items[self.current].checked = not self.items[self.current].checked
            self.selectionChanged.emit()
            self.update()
            return
        if event.modifiers() & Qt.ControlModifier and key == Qt.Key_A:
            self.set_all_checked(not self.all_checked())
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_current()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        i = self._index_at(event.pos())
        if i < 0:
            return
        self.current = i
        self.update()
        menu = QMenu(self)
        a_r = menu.addAction("顺时针旋转 90°")
        a_l = menu.addAction("逆时针旋转 90°")
        a_reset = menu.addAction("重置旋转")
        menu.addSeparator()
        a_toggle = menu.addAction("取消勾选" if self.items[i].checked else "勾选此页")
        menu.addSeparator()
        a_del = menu.addAction("移除此页")
        a_del_un = menu.addAction("移除所有未勾选的页")
        act = menu.exec(event.globalPos())
        if act == a_r:
            self.rotate_current(90)
        elif act == a_l:
            self.rotate_current(-90)
        elif act == a_reset:
            self.items[i].rotation = 0
            self._request_thumb(i)
            self.update()
        elif act == a_toggle:
            self.items[i].checked = not self.items[i].checked
            self.selectionChanged.emit()
            self.update()
        elif act == a_del:
            self.delete_current()
        elif act == a_del_un:
            self.delete_unchecked()
