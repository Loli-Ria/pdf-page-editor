# -*- coding: utf-8 -*-
"""一键打包：PyInstaller onedir 构建 Windows 可执行文件。

用法：
    python tools/build.py            # 增量构建
    python tools/build.py --clean    # 先删 build/ dist/

产物：dist/PDF页数编辑器/PDF页数编辑器.exe
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAME = "PDF页数编辑器"
RES = os.path.join(ROOT, "src", "pdf_editor", "resources")
ICON = os.path.join(RES, "icon.ico")

EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "tkinter",
    "unittest",
]


def main() -> int:
    clean = "--clean" in sys.argv
    if clean:
        for d in ("build", "dist"):
            p = os.path.join(ROOT, d)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
                print("removed", p)

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", NAME,
        "--paths", os.path.join(ROOT, "src"),
        "--add-data", f"{RES}{os.pathsep}pdf_editor/resources",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    if os.path.isfile(ICON):
        args += ["--icon", ICON]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    args.append(os.path.join(ROOT, "run.py"))

    print(" ".join(args))
    code = subprocess.call(args, cwd=ROOT)
    if code == 0:
        exe = os.path.join(ROOT, "dist", NAME, f"{NAME}.exe")
        print("\n构建完成：", exe)
        print("整个 dist/%s 目录一起分发即可。" % NAME)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
