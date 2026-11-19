# -*- coding: utf-8 -*-
"""主题：配色常量 + 全局 QSS。"""

from __future__ import annotations

import os

BG = "#F1F3F7"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F8F9FC"
BORDER = "#E3E7EF"
BORDER_STRONG = "#CFD6E4"
TEXT = "#1A2030"
TEXT_MUTED = "#6C7688"
TEXT_FAINT = "#98A1B3"
ACCENT = "#4F6BFF"
ACCENT_HOVER = "#3D57E8"
ACCENT_SOFT = "#EEF1FF"
DANGER = "#E5484D"
DANGER_SOFT = "#FDEEEE"
SUCCESS = "#16A34A"
SUCCESS_SOFT = "#EAF7EF"
WARN = "#F59E0B"

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif'

_RES_DIR = ""


def set_resource_dir(path: str) -> None:
    """告诉主题图片资源在哪儿（打包成 exe 后路径会变）。"""
    global _RES_DIR
    _RES_DIR = path or ""


def _img(name: str) -> str:
    path = os.path.join(_RES_DIR, name).replace("\\", "/")
    return f'url("{path}")'


def app_qss() -> str:
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: 13px;
    color: {TEXT};
}}
QWidget#Root {{ background: {BG}; }}

/* ---------------- 标题栏 ---------------- */
QWidget#TitleBar {{
    background: {SURFACE};
    border-bottom: 1px solid {BORDER};
}}
QLabel#AppTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#AppMark {{
    background: {ACCENT}; color: #FFFFFF; border-radius: 9px;
    font-size: 15px; font-weight: 700;
}}
QPushButton#WinBtn {{
    border: none; background: transparent; border-radius: 7px;
}}
QPushButton#WinBtn:hover {{ background: #EDF0F6; }}
QPushButton#WinClose {{ border: none; background: transparent; border-radius: 7px; }}
QPushButton#WinClose:hover {{ background: {DANGER}; }}

/* ---------------- 分段切换 ---------------- */
QWidget#SegBox {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QPushButton#Seg {{
    border: none; background: transparent; border-radius: 8px;
    padding: 7px 18px; color: {TEXT_MUTED}; font-weight: 500;
}}
QPushButton#Seg:hover {{ color: {TEXT}; }}
QPushButton#Seg:checked {{
    background: {SURFACE}; color: {ACCENT}; font-weight: 600;
    border: 1px solid {BORDER};
}}

/* ---------------- 卡片 ---------------- */
QFrame#Card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame#CardFlat {{
    background: {SURFACE_ALT};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; }}
QLabel#Hint {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 12px; }}
QLabel#FileTitle {{ font-size: 14px; font-weight: 600; }}

/* ---------------- 按钮 ---------------- */
QPushButton#Primary {{
    background: {ACCENT}; color: #FFFFFF; border: none; border-radius: 10px;
    padding: 11px 20px; font-size: 14px; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#Primary:pressed {{ background: #2F46C9; }}
QPushButton#Primary:disabled {{ background: #C9D2E6; color: #F4F6FB; }}

QPushButton#Ghost {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 13px; color: {TEXT};
}}
QPushButton#Ghost:hover {{ background: #F4F6FB; border-color: {BORDER_STRONG}; }}
QPushButton#Ghost:pressed {{ background: #EAEEF6; }}
QPushButton#Ghost:disabled {{ color: {TEXT_FAINT}; background: {SURFACE_ALT}; }}

QPushButton#Tiny {{
    background: transparent; border: none; border-radius: 7px;
    padding: 5px 9px; color: {TEXT_MUTED};
}}
QPushButton#Tiny:hover {{ background: #EFF2F8; color: {TEXT}; }}
QPushButton#TinyDanger:hover {{ background: {DANGER_SOFT}; color: {DANGER}; }}

/* ---------------- 文件标签 ---------------- */
QFrame#Chip {{
    background: {SURFACE_ALT}; border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#Chip:hover {{ border-color: {BORDER_STRONG}; background: {SURFACE}; }}
QPushButton#ChipClose {{
    background: transparent; border: none; border-radius: 9px;
    color: {TEXT_FAINT}; font-size: 12px; padding: 0px;
}}
QPushButton#ChipClose:hover {{ background: {DANGER_SOFT}; color: {DANGER}; }}

/* ---------------- 输入 ---------------- */
QLineEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px; selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
QLineEdit:hover {{ border-color: {BORDER_STRONG}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled {{ background: {SURFACE_ALT}; color: {TEXT_FAINT}; }}

QSpinBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 8px; min-width: 46px;
}}
QSpinBox:focus {{ border-color: {ACCENT}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 10px;
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
    outline: none; padding: 4px;
}}

QCheckBox {{ spacing: 9px; }}
QCheckBox:disabled {{ color: {TEXT_FAINT}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    image: {_img("check_off.png")};
}}
QCheckBox::indicator:hover {{ image: {_img("check_off.png")}; }}
QCheckBox::indicator:checked {{ image: {_img("check_on.png")}; }}

/* ---------------- 单选卡片 ---------------- */
QFrame#RadioCard {{
    background: {SURFACE}; border: 1.5px solid {BORDER}; border-radius: 11px;
}}
QFrame#RadioCard:hover {{ border-color: {BORDER_STRONG}; background: #FBFCFE; }}
QFrame#RadioCard[checked="true"] {{
    border-color: {ACCENT}; background: {ACCENT_SOFT};
}}
QLabel#RadioTitle {{ font-size: 13px; font-weight: 600; }}
QLabel#RadioDesc {{ font-size: 12px; color: {TEXT_MUTED}; }}

/* ---------------- 滚动条 ---------------- */
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: #CDD4E2; border-radius: 4px; min-height: 32px;
}}
QScrollBar::handle:vertical:hover {{ background: #B3BCCE; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{ background: #CDD4E2; border-radius: 4px; min-width: 32px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea#SidePanel > QWidget > QWidget {{ background: transparent; }}
QWidget#SideBody {{ background: transparent; }}
QToolTip {{
    background: #22293A; color: #FFFFFF; border: none;
    padding: 6px 9px; border-radius: 7px; font-size: 12px;
}}

/* ---------------- 进度 ---------------- */
QProgressBar {{
    background: #E8ECF4; border: none; border-radius: 4px;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

QSplitter::handle {{ background: transparent; width: 0px; }}
"""
