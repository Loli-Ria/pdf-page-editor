# -*- coding: utf-8 -*-
"""左侧大预览：实时显示当前选中页，支持缩放、拖动平移，以及画笔 / 文字批注。"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QColorDialog, QComboBox, QFrame, QGraphicsPathItem,
                               QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView,
                               QHBoxLayout, QInputDialog, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core import annotate
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
    inkDone = Signal(list)
    textAt = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tool = "none"            # none / pen / text
        self.pen_color = "#E5484D"
        self.pen_width = 6.0          # 千分之一页宽
        self._drawing = False
        self._path: QPainterPath | None = None
        self._item: QGraphicsPathItem | None = None
        self._scene_rect = None

    # ---------------------------------------------------------------- 工具
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        if tool == "none":
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif tool == "pen":
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(Qt.IBeamCursor)

    def _norm(self, pos: QPointF) -> tuple[float, float] | None:
        r = self._scene_rect
        if r is None or r.width() <= 0 or r.height() <= 0:
            return None
        x = (pos.x() - r.x()) / r.width()
        y = (pos.y() - r.y()) / r.height()
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    # ---------------------------------------------------------------- 事件
    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta:
            self.zoomed.emit(1.15 if delta > 0 else 1 / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.tool == "pen" and event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            norm = self._norm(pos)
            if norm is None:
                return
            self._drawing = True
            self._path = QPainterPath(QPointF(pos))
            pen = QPen(QColor(self.pen_color))
            pen.setWidthF(max(1.0, self.pen_width * self._scene_rect.width() / 1000.0))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            self._item = QGraphicsPathItem(self._path)
            self._item.setPen(pen)
            self._item.setZValue(10)
            self.scene().addItem(self._item)
            event.accept()
            return
        if self.tool == "text" and event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            norm = self._norm(pos)
            if norm is not None:
                self.textAt.emit(norm[0], norm[1])
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drawing and self._path is not None:
            pos = self.mapToScene(event.position().toPoint())
            self._path.lineTo(pos)
            if self._item is not None:
                self._item.setPath(self._path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drawing and self._path is not None:
            self._drawing = False
            pts: list[tuple[float, float]] = []
            for i in range(self._path.elementCount()):
                el = self._path.elementAt(i)
                norm = self._norm(QPointF(el.x, el.y))
                if norm:
                    pts.append(norm)
            if self._item is not None:
                self.scene().removeItem(self._item)
            self._item = None
            self._path = None
            if len(pts) >= 2:
                self.inkDone.emit(pts)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreviewPanel(QFrame):
    """当前页大图预览 + 批注草稿。"""

    inkAdded = Signal(list)
    textAdded = Signal(float, float, str)
    undoRequested = Signal()
    notesCleared = Signal()

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
        self._pen_color = "#E5484D"
        self._pen_width = 6.0
        self._text_color = "#1A2030"
        self._text_font = "微软雅黑"
        self._text_size = 0.045
        self._note_items: list = []
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

        # 批注工具条（两行，窄预览栏也放得下）
        self.btn_pen = QPushButton("画笔")
        self.btn_text = QPushButton("文字")
        self.btn_color = QPushButton("颜色")
        self.btn_width = QPushButton("中笔")
        self.btn_undo = QPushButton("撤销")
        self.btn_clear = QPushButton("清空")
        for b in (self.btn_pen, self.btn_text, self.btn_color, self.btn_width,
                  self.btn_undo, self.btn_clear):
            b.setObjectName("Tiny")
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(26)
            b.setCheckable(b in (self.btn_pen, self.btn_text))
        self.btn_pen.setToolTip("画笔：在预览图上手写批注")
        self.btn_text.setToolTip("文字：点一下页面，输入文字贴上去")
        self.btn_color.setToolTip("选择笔迹 / 文字颜色")
        self.btn_width.setToolTip("切换笔迹粗细")
        self.btn_undo.setToolTip("撤销上一笔（Ctrl+Z）")
        self.btn_clear.setToolTip("清空当前页的所有批注")

        self.font_box = QComboBox()
        self.font_box.addItems(annotate.FONT_NAMES)
        self.font_box.setMinimumHeight(26)
        self.font_box.setToolTip("文字字体")

        self.tools_row = QWidget()
        tv = QVBoxLayout(self.tools_row)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(6)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        for b in (self.btn_pen, self.btn_text, self.btn_color):
            row1.addWidget(b)
        row1.addStretch(1)
        row1.addWidget(self.btn_undo)
        row1.addWidget(self.btn_clear)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(self.btn_width)
        row2.addWidget(QLabel("字体"))
        row2.addWidget(self.font_box, 1)
        tv.addLayout(row1)
        tv.addLayout(row2)
        lay.addWidget(self.tools_row)

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
        self.view.inkDone.connect(self.inkAdded.emit)
        self.view.textAt.connect(self._on_text_at)
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

        self.btn_pen.toggled.connect(self._on_tool_toggle)
        self.btn_text.toggled.connect(self._on_tool_toggle)
        self.btn_color.clicked.connect(self._pick_color)
        self.btn_width.clicked.connect(self._cycle_width)
        self.btn_undo.clicked.connect(self.undoRequested.emit)
        self.btn_clear.clicked.connect(self.notesCleared.emit)
        self.font_box.currentTextChanged.connect(self._on_font_changed)
        self._update_controls()

    # -------------------------------------------------------------- 对外接口
    def show_ref(self, sources: list, ref, notes: list | None = None) -> None:
        """显示 sources[ref.src] 的第 ref.index 页，并叠上已有批注。"""
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
        self._pending_notes = list(notes or [])
        task = _RenderTask(self._signals, self._token, list(sources), ref,
                           RENDER_SIDE)
        self._pool.start(task)

    def refresh_notes(self, notes: list) -> None:
        """批注变化后重画（不重新渲染页面）。"""
        self._pending_notes = list(notes or [])
        self._paint_notes()

    def clear(self) -> None:
        self._token += 1
        self._path = ""
        self._index = -1
        self._has_image = False
        self._pending_notes = []
        self.item.setPixmap(QPixmap())
        self.scene.setSceneRect(0, 0, 0, 0)
        self._paint_notes()
        self.page_label.setText("未选择")
        self.hint.setText("在右侧点选一页，这里会放大显示")
        self.hint.show()
        self._update_controls()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.2, min(4.0, zoom))
        self._apply()

    def current_tool(self) -> str:
        return self.view.tool

    def pen_style(self) -> tuple[str, float]:
        """当前画笔的 (颜色, 粗细)。"""
        return self._pen_color, self._pen_width

    def text_style(self) -> tuple[str, str, float]:
        """当前文字的 (颜色, 字体, 字高比例)。"""
        return self._text_color, self._text_font, self._text_size

    # ------------------------------------------------------------------ 内部
    def _on_tool_toggle(self, _checked: bool) -> None:
        if self.btn_pen.isChecked():
            self.btn_text.setChecked(False)
            self.view.set_tool("pen")
        elif self.btn_text.isChecked():
            self.btn_pen.setChecked(False)
            self.view.set_tool("text")
        else:
            self.view.set_tool("none")

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._pen_color), self, "选择颜色")
        if not color.isValid():
            return
        self._pen_color = color.name()
        self._text_color = color.name()
        self.btn_color.setStyleSheet(
            f"QPushButton {{ background: {self._pen_color}; color: white;"
            f"border: 1px solid {self._pen_color}; border-radius: 7px; }}")

    def _cycle_width(self) -> None:
        widths = [(3.0, "细笔"), (6.0, "中笔"), (10.0, "粗笔"), (16.0, "特粗")]
        try:
            idx = [v for v, _ in widths].index(self._pen_width)
        except ValueError:
            idx = 0
        value, label = widths[(idx + 1) % len(widths)]
        self._pen_width = value
        self.view.pen_width = value
        self.btn_width.setText(label)

    def _on_font_changed(self, name: str) -> None:
        self._text_font = name or "微软雅黑"

    def _on_text_at(self, x: float, y: float) -> None:
        text, ok = QInputDialog.getText(self, "插入文字", "文字内容：")
        if ok and text.strip():
            self.textAdded.emit(x, y, text)

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
        self._paint_notes()

    def _on_fail(self, msg: str) -> None:
        self.hint.setText(f"这一页没能显示：{msg}")
        self.hint.show()

    # ---------------------------------------------------------------- 批注
    def _paint_notes(self) -> None:
        for it in self._note_items:
            self.scene.removeItem(it)
        self._note_items.clear()
        pm = self.item.pixmap()
        if pm.isNull() or not self._has_image:
            return
        w = float(pm.width())
        h = float(pm.height())
        for note in getattr(self, "_pending_notes", []):
            if isinstance(note, annotate.InkStroke):
                path = QPainterPath()
                pts = [QPointF(p[0] * w, p[1] * h) for p in note.points]
                if len(pts) < 2:
                    continue
                path.moveTo(pts[0])
                for p in pts[1:]:
                    path.lineTo(p)
                item = QGraphicsPathItem(path)
                pen = QPen(QColor(note.color))
                pen.setWidthF(max(1.0, note.width * w / 1000.0))
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                item.setPen(pen)
                item.setZValue(10)
                self.scene.addItem(item)
                self._note_items.append(item)
            elif isinstance(note, annotate.TextMark):
                item = QGraphicsSimpleTextItem(note.text)
                font = QFont(note.font)
                font.setPixelSize(max(6, int(note.size * h)))
                item.setFont(font)
                item.setBrush(QBrush(QColor(note.color)))
                item.setPos(note.x * w, note.y * h)
                item.setZValue(11)
                self.scene.addItem(item)
                self._note_items.append(item)

    def _apply(self) -> None:
        if not self._has_image:
            self._update_controls()
            return
        self.view.resetTransform()
        self.view.fitInView(self.item, Qt.KeepAspectRatio)
        if abs(self._zoom - 1.0) > 1e-6:
            self.view.scale(self._zoom, self._zoom)
        self.view._scene_rect = self.scene.sceneRect()
        self._update_controls()

    def _update_controls(self) -> None:
        on = self._has_image
        self.btn_out.setEnabled(on and self._zoom > 0.21)
        self.btn_in.setEnabled(on and self._zoom < 3.9)
        self.btn_fit.setEnabled(on)
        self.btn_pen.setEnabled(on)
        self.btn_text.setEnabled(on)
        self.btn_undo.setEnabled(on)
        self.btn_clear.setEnabled(on)
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply()
