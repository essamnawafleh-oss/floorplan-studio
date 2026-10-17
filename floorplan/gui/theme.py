"""Themes: every colour of the UI comes from a token set, so the app looks the
same whatever the Windows light/dark setting is. A theme can also be loaded
from a JSON file with the same keys (see docs/theme_example.json)."""

from __future__ import annotations

import json

from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

# UI tokens
BUILTIN: dict[str, dict] = {
    "light": dict(
        label=("فاتح", "Light"),
        window="#f6f7f9", card="#ffffff", border="#e1e4e8", input="#ffffff", input_border="#cfd5dc",
        text="#1f252d", muted="#6a717b", hover="#eef2f7", selection="#d6e4fb", canvas="#eceef1",
        accent="#2f6fd6", accent_text="#ffffff", warn="#9a5b00", plan="light"),
    "dark": dict(
        label=("داكن", "Dark"),
        window="#16191e", card="#1f2329", border="#2e333b", input="#262b32", input_border="#3a4049",
        text="#e7eaee", muted="#9aa3ad", hover="#2a3038", selection="#2c4a7a", canvas="#111317",
        accent="#4c8dff", accent_text="#ffffff", warn="#f0b45a", plan="dark"),
    "midnight": dict(
        label=("كحلي", "Midnight"),
        window="#0f1a2b", card="#16243a", border="#24344f", input="#1b2b45", input_border="#2f4466",
        text="#e6edf7", muted="#93a4bf", hover="#1f3150", selection="#2b4f86", canvas="#0b1422",
        accent="#3fb6a8", accent_text="#0b1422", warn="#f2c14e", plan="dark"),
    "sand": dict(
        label=("رملي", "Sand"),
        window="#f4efe6", card="#fffaf2", border="#e4d9c6", input="#fffdf8", input_border="#d6c7ad",
        text="#2c261d", muted="#7a6d5a", hover="#efe5d3", selection="#ead7b4", canvas="#e9e1d3",
        accent="#b0672c", accent_text="#ffffff", warn="#9a4b00", plan="light"),
}

# Plan drawing colours (the plan is drawn natively, so it follows the theme too)
PLAN = {
    "light": dict(paper="#ffffff", wall="#26282c", ink="#3a3d42", dim="#7a7f87", text="#22252a",
                  text2="#555a62", glass="#4a7fb5", window="#ffffff", select="#2f6fd6",
                  zones={"public": "#f6ead7", "service": "#e3efe4", "private": "#e4ebf6", "circulation": "#f1f1ef"}),
    "dark": dict(paper="#1b1f24", wall="#d9dde3", ink="#c4cad2", dim="#8a929c", text="#eef1f4",
                 text2="#aab2bc", glass="#6aa7e6", window="#1b1f24", select="#4c8dff",
                 zones={"public": "#3b3326", "service": "#28382b", "private": "#2a3344", "circulation": "#2a2d31"}),
}

DEFAULTS = dict(theme="system", accent="", font_family="Segoe UI", font_size=10, plan_theme="match")


def resolve(name: str, custom: dict | None = None) -> dict:
    """Theme name ('system', a built-in key or 'custom') -> token dict."""
    if name == "custom" and custom:
        base = dict(BUILTIN["dark" if _is_dark(custom.get("window", "#ffffff")) else "light"])
        base.update(custom)
        return base
    if name == "system":
        scheme = QGuiApplication.styleHints().colorScheme()
        from PySide6.QtCore import Qt
        name = "dark" if scheme == Qt.ColorScheme.Dark else "light"
    return dict(BUILTIN.get(name, BUILTIN["light"]))


def _is_dark(hex_color: str) -> bool:
    return QColor(hex_color).lightness() < 128


def load_theme_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in ("window", "card", "text", "accent") if k not in data]
    if missing:
        raise ValueError("Missing keys: " + ", ".join(missing))
    return data


def plan_colors(tokens: dict, plan_theme: str) -> dict:
    key = tokens.get("plan", "light") if plan_theme == "match" else plan_theme
    return PLAN.get(key, PLAN["light"])


def stylesheet(t: dict) -> str:
    return f"""
QWidget {{ color: {t['text']}; }}
QMainWindow, QDialog, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {t['window']}; }}
QGroupBox {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 8px; margin-top: 14px;
            padding: 12px 8px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 10px; right: 10px;
                   padding: 0 4px; color: {t['text']}; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {t['muted']}; }}
QPushButton {{ background: {t['card']}; border: 1px solid {t['input_border']}; border-radius: 6px; padding: 5px 10px; }}
QPushButton:hover {{ background: {t['hover']}; }}
QPushButton#primary {{ background: {t['accent']}; color: {t['accent_text']}; border: none; font-weight: 600; padding: 9px; }}
QPushButton#primary:hover {{ background: {QColor(t['accent']).darker(112).name()}; }}
QPushButton#primary:disabled {{ background: {QColor(t['accent']).lighter(140).name()}; }}
QToolBar {{ background: {t['card']}; border: none; border-bottom: 1px solid {t['border']}; spacing: 6px; padding: 4px; }}
QToolButton {{ padding: 5px 10px; border-radius: 6px; background: transparent; }}
QToolButton:hover {{ background: {t['hover']}; }}
QToolButton#variant {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}
QToolButton#variant:hover {{ border-color: {t['accent']}; }}
QLabel#status {{ color: {t['muted']}; padding: 4px 10px; background: {t['card']}; border-top: 1px solid {t['border']}; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; background: {t['card']}; }}
QTabBar::tab {{ background: {t['window']}; border: 1px solid {t['border']}; padding: 6px 12px; margin: 0 1px; }}
QTabBar::tab:selected {{ background: {t['card']}; border-bottom-color: {t['card']}; }}
QTableWidget, QListWidget {{ background: {t['card']}; alternate-background-color: {t['window']};
                            gridline-color: {t['border']}; border: none; }}
QHeaderView::section {{ background: {t['window']}; color: {t['muted']}; border: none;
                       border-bottom: 1px solid {t['border']}; padding: 5px; }}
QLineEdit {{ background: {t['input']}; color: {t['text']}; border: 1px solid {t['input_border']};
            border-radius: 5px; padding: 3px 6px; min-height: 22px; }}
QLineEdit:disabled {{ background: {t['window']}; color: {t['muted']}; }}
QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox {{ min-height: 24px; }}
QComboBox QAbstractItemView {{ background: {t['card']}; color: {t['text']}; selection-background-color: {t['selection']}; }}
QMenu {{ background: {t['card']}; border: 1px solid {t['border']}; }}
QMenu::item:selected {{ background: {t['selection']}; }}
QSplitter::handle {{ background: {t['border']}; }}
QCheckBox::indicator, QListView::indicator, QGroupBox::indicator {{ width: 15px; height: 15px; border-radius: 3px;
            border: 1.5px solid {t['muted']}; background: {t['input']}; }}
QCheckBox::indicator:checked, QListView::indicator:checked, QGroupBox::indicator:checked {{
            background: {t['accent']}; border-color: {t['accent']}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1.5px solid {t['muted']};
            background: {t['input']}; }}
QRadioButton::indicator:checked {{ background: {t['accent']}; border: 3px solid {t['input']};
            outline: none; }}
QScrollBar {{ background: {t['window']}; }}
"""


def palette(t: dict) -> QPalette:
    p = QPalette()
    c = lambda k: QColor(t[k])
    for group in (QPalette.Active, QPalette.Inactive):
        p.setColor(group, QPalette.Window, c("window"))
        p.setColor(group, QPalette.WindowText, c("text"))
        p.setColor(group, QPalette.Base, c("input"))
        p.setColor(group, QPalette.AlternateBase, c("window"))
        p.setColor(group, QPalette.Text, c("text"))
        p.setColor(group, QPalette.Button, c("card"))
        p.setColor(group, QPalette.ButtonText, c("text"))
        p.setColor(group, QPalette.Highlight, c("accent"))
        p.setColor(group, QPalette.HighlightedText, c("accent_text"))
        p.setColor(group, QPalette.ToolTipBase, c("card"))
        p.setColor(group, QPalette.ToolTipText, c("text"))
        p.setColor(group, QPalette.PlaceholderText, c("muted"))
        p.setColor(group, QPalette.Link, c("accent"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c("muted"))
    for role, key in ((QPalette.Base, "window"), (QPalette.Window, "window"), (QPalette.Button, "card"),
                      (QPalette.AlternateBase, "window"), (QPalette.Highlight, "border")):
        p.setColor(QPalette.Disabled, role, c(key))
    return p


def apply(app, prefs: dict) -> dict:
    """Apply theme + font to the whole app. Returns the resolved tokens."""
    t = resolve(prefs.get("theme", "system"), prefs.get("custom_theme"))
    if prefs.get("accent"):
        t["accent"] = prefs["accent"]
    app.setPalette(palette(t))
    app.setStyleSheet(stylesheet(t))
    font = QFont(prefs.get("font_family") or DEFAULTS["font_family"])
    font.setPointSize(int(prefs.get("font_size") or DEFAULTS["font_size"]))
    app.setFont(font)
    return t
