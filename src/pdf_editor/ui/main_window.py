# -*- coding: utf-8 -*-
"""主窗口：标题栏 + 模式切换 + 两个工作页 + 浮层提示。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QLabel,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import theme
from .widgets import FramelessWindow, SegmentedControl, TitleBar
from .merge_page import MergePage
from .split_page import SplitPage


class Toast(QLabel):
    """底部居中的轻提示。"""

    COLORS = {
        "info": "#22293A",
        "ok": "#12784A",
        "error": "#B4231F",
    }

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWordWrap(True)
        self.setMaximumWidth(620)
        self.setAlignment(Qt.AlignCenter)
        f = QFont()
        f.setPixelSize(13)
        self.setFont(f)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(240)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_msg(self, text: str, kind: str = "info") -> None:
        bg = self.COLORS.get(kind, self.COLORS["info"])
        self.setStyleSheet(
            f"background: {bg}; color: #FFFFFF; border-radius: 10px;"
            f"padding: 11px 20px;")
        self.setText(text)
        fm = self.fontMetrics()
        need = fm.horizontalAdvance(text) + 48
        self.setFixedWidth(max(180, min(need, 620)))
        self.adjustSize()
        self._reposition()
        self._anim.stop()
        self._effect.setOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(2800)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_if_done)
        self._anim.start()

    def _hide_if_done(self) -> None:
        try:
            self._anim.finished.disconnect(self._hide_if_done)
        except (RuntimeError, TypeError):
            pass
        if self._effect.opacity() <= 0.01:
            self.hide()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        max_w = max(220, parent.width() - 80)
        self.setMaximumWidth(max_w)
        w = min(self.sizeHint().width() + 4, max_w)
        self.setFixedWidth(w)
        self.adjustSize()
        x = (parent.width() - w) // 2
        y = parent.height() - self.height() - 26
        self.move(x, y)


class MainWindow(FramelessWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF 页数编辑器")
        self.resize(1300, 840)
        self.setMinimumSize(1080, 690)
        self.setAcceptDrops(True)
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(0)

        self.titlebar = TitleBar("PDF 页数编辑器")
        outer.addWidget(self.titlebar)

        self.seg = SegmentedControl(["拆分 PDF", "合并文件"])
        self.seg.setFixedWidth(230)
        host = self.titlebar.center_host.layout()
        host.addStretch(1)
        host.addWidget(self.seg)
        host.addStretch(1)

        self.stack = QStackedWidget()
        self.split_page = SplitPage()
        self.merge_page = MergePage()
        self.stack.addWidget(self.split_page)
        self.stack.addWidget(self.merge_page)
        outer.addWidget(self.stack, 1)

        self.seg.changed.connect(self.stack.setCurrentIndex)
        self.split_page.toast.connect(self._toast)
        self.merge_page.toast.connect(self._toast)

        self.toast = Toast(self)

    def _toast(self, text: str, kind: str = "info") -> None:
        self.toast.show_msg(text, kind)

    # -------------------------------------------------------------- 整窗拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, "dragEnterEvent"):
            page.dragEnterEvent(event)
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, "dragMoveEvent"):
            page.dragMoveEvent(event)
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, "dropEvent"):
            page.dropEvent(event)
        else:
            super().dropEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast"):
            self.toast._reposition()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        # 最大化时收起边缘留白，避免标题栏离屏幕边缘有空隙
        if event.type() == event.Type.WindowStateChange:
            m = 0 if self.isMaximized() or self.isFullScreen() else 6
            self.layout().setContentsMargins(m, m, m, m)
