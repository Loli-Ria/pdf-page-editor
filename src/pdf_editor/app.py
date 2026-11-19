# -*- coding: utf-8 -*-
"""PDF 页数编辑器 · 桌面程序入口。"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from .ui import theme
from .ui.main_window import MainWindow

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def resource_path(name: str) -> str:
    """打包成 exe 后资源位于 _MEIPASS/pdf_editor/resources，源码运行时在包内。"""
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        cand = os.path.join(base, "pdf_editor", "resources", name)
        if os.path.exists(cand):
            return cand
        return os.path.join(base, name)
    return os.path.join(RESOURCES, name)


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("PDF 页数编辑器")
    app.setOrganizationName("CyreneTools")

    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(13)
    app.setFont(font)

    theme.set_resource_dir(RESOURCES)
    app.setStyleSheet(theme.app_qss())

    icon = resource_path("icon.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
