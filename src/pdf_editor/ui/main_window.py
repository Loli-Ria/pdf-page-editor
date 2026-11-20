# -*- coding: utf-8 -*-
"""主窗口：标题栏 + 页面编辑区 + 浮层提示。"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QLabel, QVBoxLayout,
                               QWidget)

from .split_page import SplitPage
from .widgets import FramelessWindow, TitleBar


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

        # 只有一个工作区，标题栏中间放一枚静态标识（不再是可切换的标签）
        self.badge = QLabel("页面编辑")
        self.badge.setObjectName("PageBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFixedHeight(32)
        host = self.titlebar.center_host.layout()
        host.addStretch(1)
        host.addWidget(self.badge)
        host.addStretch(1)

        self.split_page = SplitPage()
        outer.addWidget(self.split_page, 1)

        self.split_page.toast.connect(self._toast)
        self.toast = Toast(self)

    def _toast(self, text: str, kind: str = "info") -> None:
        self.toast.show_msg(text, kind)

    # -------------------------------------------------------------- 整窗拖放
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        self.split_page.dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.split_page.dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        self.split_page.dropEvent(event)

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
