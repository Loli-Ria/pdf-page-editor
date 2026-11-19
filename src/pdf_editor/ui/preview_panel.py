# -*- coding: utf-8 -*-
"""左侧大预览：实时显示当前选中页，支持缩放与拖动平移。"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core import engine as E
from . import theme

RENDER_SIDE = 1800  # 预览渲染分辨率（足够放大到 200% 仍清晰）


class _Signals(QObject):
    done = Signal(bytes, int)
    fail = Signal(str)


class _RenderTask(QRunnable):
    def __init__(self, signals: _Signals, token: int, sources: list,
                 ref, max_side: int) -> None:
        super().__init__()
        self.signals = signals
        self.token = token
        self.sources = sources
        self.ref = ref
        self.max_side = max_side

    def run(self) -> None:  # noqa: D401
        try:
            data = E.render_ref_png(self.sources, self.ref, self.max_side)
        except Exception as exc:  # noqa: BLE001
            self.signals.fail.emit(str(exc))
            return
        self.signals.done.emit(data, self.token)


class _View(QGraphicsView):
    zoomed = Signal(float)

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.zoomed.emit(1.15 if delta > 0 else 1 / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)


class PreviewPanel(QFrame):
    """当前页大图预览。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._path = ""
        self._index = -1
        self._rotation = 0
        self._token = 0
        self._zoom = 1.0
        self._has_image = False
        self._pool = QThreadPool.globalInstance()
        self._signals = _Signals()
        self._signals.done.connect(self._on_rendered)
        self._signals.fail.connect(self._on_fail)
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("页面预览")
        tf = title.font()
        tf.setPixelSize(13)
        tf.setBold(True)
        title.setFont(tf)
        self.page_label = QLabel("未选择")
        self.page_label.setObjectName("Hint")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.page_label)
        lay.addLayout(head)

        self.view = _View()
        self.scene = QGraphicsScene(self.view)
        self.view.setScene(self.scene)
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene.addItem(self.item)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.view.setRenderHint(QPainter.Antialiasing, True)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setStyleSheet(
            f"QGraphicsView {{ background: {theme.SURFACE_ALT};"
            f"border: 1px solid {theme.BORDER}; border-radius: 10px; }}")
        self.view.zoomed.connect(self._on_wheel_zoom)
        lay.addWidget(self.view, 1)

        self.hint = QLabel("在右侧点选一页，这里会放大显示")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setObjectName("Hint")
        self.hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self.hint)
        self.hint.hide()

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_out = QPushButton("－")
        self.btn_in = QPushButton("＋")
        self.btn_fit = QPushButton("适应窗口")
        for b in (self.btn_out, self.btn_in):
            b.setObjectName("Tiny")
            b.setFixedSize(30, 28)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_fit.setObjectName("Tiny")
        self.btn_fit.setCursor(Qt.PointingHandCursor)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("Hint")
        self.zoom_label.setFixedWidth(46)
        self.zoom_label.setAlignment(Qt.AlignCenter)

        bar.addWidget(self.btn_out)
        bar.addWidget(self.zoom_label)
        bar.addWidget(self.btn_in)
        bar.addWidget(self.btn_fit)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.btn_out.clicked.connect(lambda: self.set_zoom(self._zoom / 1.2))
        self.btn_in.clicked.connect(lambda: self.set_zoom(self._zoom * 1.2))
        self.btn_fit.clicked.connect(lambda: self.set_zoom(1.0))
        self._update_controls()

    # -------------------------------------------------------------- 对外接口
    def show_ref(self, sources: list, ref) -> None:
        """显示 sources[ref.src] 的第 ref.index 页。"""
        if not (0 <= ref.src < len(sources)):
            self.clear()
            return
        src = sources[ref.src]
        self._path = src.path
        self._index = ref.index
        self._rotation = ref.rotation
        self._token += 1
        if len(sources) > 1:
            self.page_label.setText(f"{ref.index + 1} 页 · 文件 {ref.src + 1}")
        else:
            self.page_label.setText(f"第 {ref.index + 1} 页")
        self.page_label.setToolTip(src.name)
        self.hint.hide()
        task = _RenderTask(self._signals, self._token, list(sources), ref,
                           RENDER_SIDE)
        self._pool.start(task)

    def clear(self) -> None:
        self._token += 1
        self._path = ""
        self._index = -1
        self._has_image = False
        self.item.setPixmap(QPixmap())
        self.scene.setSceneRect(0, 0, 0, 0)
        self.page_label.setText("未选择")
        self.hint.setText("在右侧点选一页，这里会放大显示")
        self.hint.show()
        self._update_controls()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.2, min(4.0, zoom))
        self._apply()

    # ------------------------------------------------------------------ 内部
    def _on_wheel_zoom(self, factor: float) -> None:
        self.set_zoom(self._zoom * factor)

    def _on_rendered(self, data: bytes, token: int) -> None:
        if token != self._token or not data:
            return
        img = QImage()
        if not img.loadFromData(data):
            return
        pm = QPixmap.fromImage(img)
        self.item.setPixmap(pm)
        self.scene.setSceneRect(pm.rect())
        self._has_image = True
        self._zoom = 1.0
        self._apply()

    def _on_fail(self, msg: str) -> None:
        self.hint.setText(f"这一页没能显示：{msg}")
        self.hint.show()

    def _apply(self) -> None:
        if not self._has_image:
            self._update_controls()
            return
        self.view.resetTransform()
        self.view.fitInView(self.item, Qt.KeepAspectRatio)
        if abs(self._zoom - 1.0) > 1e-6:
            self.view.scale(self._zoom, self._zoom)
        self._update_controls()

    def _update_controls(self) -> None:
        on = self._has_image
        self.btn_out.setEnabled(on and self._zoom > 0.21)
        self.btn_in.setEnabled(on and self._zoom < 3.9)
        self.btn_fit.setEnabled(on)
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()
