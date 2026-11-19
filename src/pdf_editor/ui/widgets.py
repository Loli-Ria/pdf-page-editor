# -*- coding: utf-8 -*-
"""通用控件：无边框窗口、标题栏、单选卡片、拖放区、分段控件。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import theme


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# --------------------------------------------------------------------------
# 无边框窗口
# --------------------------------------------------------------------------

class FramelessWindow(QWidget):
    """无边框窗口：标题栏用系统 startSystemMove 拖动，边缘可缩放。"""

    EDGE = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setObjectName("Root")
        self.setMouseTracking(True)

    def _edges_at(self, pos: QPoint) -> int:
        if self.isMaximized() or self.isFullScreen():
            return 0
        m = self.EDGE
        r = self.rect()
        edges = 0
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge.value
        if pos.x() >= r.width() - m:
            edges |= Qt.Edge.RightEdge.value
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge.value
        if pos.y() >= r.height() - m:
            edges |= Qt.Edge.BottomEdge.value
        return edges

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        edges = self._edges_at(event.position().toPoint())
        L, R = Qt.Edge.LeftEdge.value, Qt.Edge.RightEdge.value
        T, B = Qt.Edge.TopEdge.value, Qt.Edge.BottomEdge.value
        if edges:
            if (edges & L) and (edges & T) or (edges & R) and (edges & B):
                self.setCursor(Qt.SizeFDiagCursor)
            elif (edges & L) and (edges & B) or (edges & R) and (edges & T):
                self.setCursor(Qt.SizeBDiagCursor)
            elif edges & (L | R):
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(Qt.Edges(edges))
                    return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().mouseReleaseEvent(event)


# --------------------------------------------------------------------------
# 窗口按钮
# --------------------------------------------------------------------------

class WindowButton(QPushButton):
    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(38, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("WinClose" if kind == "close" else "WinBtn")
        self.setFlat(True)
        tips = {"min": "最小化", "max": "最大化", "close": "关闭"}
        self.setToolTip(tips.get(kind, ""))

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse()
        color = QColor("#FFFFFF") if (self.kind == "close" and hover) else QColor("#3E4759")
        p.setPen(QPen(color, 1.5))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        if self.kind == "min":
            p.drawLine(int(cx - 5), int(cy), int(cx + 5), int(cy))
        elif self.kind == "max":
            p.drawRect(QRectF(cx - 4.5, cy - 4.5, 9, 9))
        else:
            p.drawLine(int(cx - 4), int(cy - 4), int(cx + 4), int(cy + 4))
            p.drawLine(int(cx + 4), int(cy - 4), int(cx - 4), int(cy + 4))

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


# --------------------------------------------------------------------------
# 标题栏
# --------------------------------------------------------------------------

class TitleBar(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(54)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(10)

        mark = QLabel("P")
        mark.setObjectName("AppMark")
        mark.setFixedSize(28, 28)
        mark.setAlignment(Qt.AlignCenter)
        f = QFont(theme.FONT_FAMILY.split(",")[0].strip('"'))
        f.setPixelSize(16)
        f.setBold(True)
        mark.setFont(f)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("AppTitle")

        lay.addWidget(mark)
        lay.addWidget(self.title_label)
        lay.addSpacing(6)

        self.center_host = QWidget()
        self.center_host.setLayout(QHBoxLayout())
        self.center_host.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.center_host, 1)

        self.btn_min = WindowButton("min")
        self.btn_max = WindowButton("max")
        self.btn_close = WindowButton("close")
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_close)

        self.btn_min.clicked.connect(lambda: self.window().showMinimized())
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(lambda: self.window().close())

    def _toggle_max(self) -> None:
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._toggle_max()


# --------------------------------------------------------------------------
# 分段控件
# --------------------------------------------------------------------------

class SegmentedControl(QWidget):
    changed = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.buttons: list[QPushButton] = []
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.set_current(idx, emit=True))
            lay.addWidget(b)
            self.buttons.append(b)
        if self.buttons:
            self.buttons[0].setChecked(True)

    def set_current(self, index: int, emit: bool = False) -> None:
        for i, b in enumerate(self.buttons):
            b.setChecked(i == index)
        if emit:
            self.changed.emit(index)

    def current(self) -> int:
        for i, b in enumerate(self.buttons):
            if b.isChecked():
                return i
        return 0


# --------------------------------------------------------------------------
# 单选卡片
# --------------------------------------------------------------------------

class RadioCard(QFrame):
    clicked = Signal()

    def __init__(self, title: str, desc: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RadioCard")
        self.setProperty("checked", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 40, 10)
        lay.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("RadioTitle")
        lay.addWidget(self.title_label)
        self.desc_label = QLabel(desc)
        self.desc_label.setObjectName("RadioDesc")
        self.desc_label.setWordWrap(True)
        self.desc_label.setVisible(bool(desc))
        lay.addWidget(self.desc_label)

    def set_checked(self, checked: bool) -> None:
        self.setProperty("checked", "true" if checked else "false")
        repolish(self)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            return max(self.minimumHeight(), lay.heightForWidth(w))
        return max(self.minimumHeight(), super().heightForWidth(w))

    def is_checked(self) -> bool:
        return self.property("checked") == "true"

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() - 22, self.height() / 2
        checked = self.is_checked()
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawEllipse(QRectF(cx - 8, cy - 8, 16, 16))
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.BORDER_STRONG), 1.5))
            p.drawEllipse(QRectF(cx - 8, cy - 8, 16, 16))


class RadioCardGroup(QWidget):
    changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.cards: list[RadioCard] = []

    def add_card(self, title: str, desc: str = "") -> RadioCard:
        card = RadioCard(title, desc)
        card.clicked.connect(lambda c=card: self._select(c))
        self.cards.append(card)
        self._layout.addWidget(card)
        if len(self.cards) == 1:
            card.set_checked(True)
        return card

    def _select(self, card: RadioCard) -> None:
        for c in self.cards:
            c.set_checked(c is card)
        self.changed.emit(self.cards.index(card))

    def current_index(self) -> int:
        for i, c in enumerate(self.cards):
            if c.is_checked():
                return i
        return 0

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self.cards):
            self._select(self.cards[index])


# --------------------------------------------------------------------------
# 拖放区
# --------------------------------------------------------------------------

class DropZone(QFrame):
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self, title: str, subtitle: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(96)
        self._active = False
        self.setStyleSheet(f"""
            QFrame#DropZone {{
                border: 2px dashed {theme.BORDER_STRONG};
                border-radius: 12px;
                background: {theme.SURFACE_ALT};
            }}
            QFrame#DropZone[active="true"] {{
                border-color: {theme.ACCENT};
                background: {theme.ACCENT_SOFT};
            }}
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        f = QFont(t.font())
        f.setPixelSize(14)
        f.setBold(True)
        t.setFont(f)
        s = QLabel(subtitle)
        s.setObjectName("Hint")
        s.setAlignment(Qt.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addStretch(1)

    def _set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.setProperty("active", "true" if active else "false")
            repolish(self)

    @staticmethod
    def _local_files(event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        out = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p:
                out.append(p)
        return out

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._local_files(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self._set_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._local_files(event):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)
        files = self._local_files(event)
        if files:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self.filesDropped.emit(files)
        else:
            event.ignore()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------

def hline(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line


def vline(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setFixedWidth(1)
    line.setStyleSheet(f"background: {theme.BORDER};")
    return line


def hint_card(title: str, rows: list[tuple[str, str]],
              parent: QWidget | None = None) -> QFrame:
    """右侧面板的浅色小贴士卡片：左边键名，右边说明。"""
    card = QFrame(parent)
    card.setObjectName("Card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(9)

    head = QLabel(title)
    f = QFont()
    f.setPixelSize(12)
    f.setBold(True)
    head.setFont(f)
    head.setStyleSheet(f"color: {theme.TEXT_MUTED};")
    lay.addWidget(head)

    for key, desc in rows:
        row = QHBoxLayout()
        row.setSpacing(10)
        k = QLabel(key)
        k.setFixedWidth(72)
        k.setAlignment(Qt.AlignCenter)
        k.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background: {theme.SURFACE_ALT};"
            f"border: 1px solid {theme.BORDER}; border-radius: 6px;"
            f"padding: 2px 6px; font-size: 11px;")
        row.addWidget(k)
        d = QLabel(desc)
        d.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 12px;")
        row.addWidget(d, 1)
        lay.addLayout(row)
    return card


# --------------------------------------------------------------------------
# 流式布局（自动换行的横向排列，用于文件标签）
# --------------------------------------------------------------------------

class FlowLayout(QLayout):
    """按行自动换行的布局。"""

    def __init__(self, parent: QWidget | None = None, margin: int = 0,
                 h_spacing: int = 8, v_spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h = h_spacing
        self._v = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y += line_h + self._v
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class FileChip(QFrame):
    """一个已导入文件的标签：类型徽标 + 文件名 + 关闭。"""

    removed = Signal(int)

    def __init__(self, index: int, name: str, kind: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Chip")
        self._index = index
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(9, 4, 5, 4)
        lay.setSpacing(6)

        is_pdf = kind == "pdf"
        tag = QLabel("PDF" if is_pdf else "图片")
        tag.setAlignment(Qt.AlignCenter)
        tag.setFixedHeight(18)
        tag.setMinimumWidth(30)
        fg = theme.ACCENT if is_pdf else theme.SUCCESS
        bg = theme.ACCENT_SOFT if is_pdf else theme.SUCCESS_SOFT
        tag.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:4px;"
            f"font-size:10px; font-weight:600; padding:0 4px;")
        lay.addWidget(tag)

        lab = QLabel(self.fontMetrics().elidedText(name, Qt.ElideMiddle, 148))
        lab.setToolTip(name)
        lab.setFixedWidth(148)
        lab.setStyleSheet(f"color:{theme.TEXT}; font-size:12px;")
        lay.addWidget(lab)

        btn = QPushButton("✕")
        btn.setObjectName("ChipClose")
        btn.setFixedSize(18, 18)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("从列表里移除这个文件")
        btn.clicked.connect(lambda: self.removed.emit(self._index))
        lay.addWidget(btn)


# --------------------------------------------------------------------------
# 右侧设置栏
# --------------------------------------------------------------------------

class SidePanel(QScrollArea):
    """右侧参数栏：内容多了可以滚动，窗口变小时不会把控件压扁。

    用法：panel = SidePanel(); panel.v.addWidget(card) ...
    """

    def __init__(self, width: int = 344, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFixedWidth(width)

        self.body = QWidget()
        self.body.setObjectName("SideBody")
        self.v = QVBoxLayout(self.body)
        self.v.setContentsMargins(0, 0, 8, 0)
        self.v.setSpacing(12)
        self.setWidget(self.body)

    def add_stretch(self) -> None:
        self.v.addStretch(1)
