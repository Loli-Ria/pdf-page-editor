# -*- coding: utf-8 -*-
"""开发时直接运行：python run.py

打包时也用这个文件作为入口。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from pdf_editor.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
