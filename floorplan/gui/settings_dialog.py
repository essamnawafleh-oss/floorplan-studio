"""Settings: theme, accent colour, UI font, plan colours, language. Changes
preview live; Cancel restores the previous look."""

from __future__ import annotations

import json

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFontComboBox,
                               QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from .strings import tr
from .theme import BUILTIN, load_theme_file

PREF_KEYS = ("theme", "accent", "font_family", "font_size", "plan_theme", "custom_theme")


class SettingsDialog(QDialog):
    def __init__(self, prefs: dict, lang: str, preview, parent=None):
        super().__init__(parent)
        self.lang, self.preview = lang, preview
        self.original = dict(prefs)
        self.prefs = dict(prefs)
        t = lambda k: tr(k, lang)
        self.setWindowTitle(t("settings_title"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.theme = QComboBox()
        self.theme.addItem(t("theme_system"), "system")
        for key, th in BUILTIN.items():
            self.theme.addItem(th["label"][0 if lang == "ar" else 1], key)
        self.theme.addItem(t("theme_custom"), "custom")
        self.theme.setCurrentIndex(max(0, self.theme.findData(prefs.get("theme", "system"))))
        row = QHBoxLayout()
        row.addWidget(self.theme, 1)
        load = QPushButton(t("theme_load"))
        load.clicked.connect(self._load_theme)
        row.addWidget(load)
        form.addRow(t("theme"), self._wrap(row))

        self.accent_btn = QPushButton()
        self.accent_btn.clicked.connect(self._pick_accent)
        reset = QPushButton(t("reset"))
        reset.clicked.connect(lambda: self._set_accent(""))
        row = QHBoxLayout()
        row.addWidget(self.accent_btn, 1)
        row.addWidget(reset)
        form.addRow(t("accent"), self._wrap(row))

        self.font = QFontComboBox()
        self.font.setCurrentFont(QFont(prefs.get("font_family", "Segoe UI")))
        form.addRow(t("ui_font"), self.font)
        self.size = QSpinBox()
        self.size.setRange(8, 18)
        self.size.setValue(int(prefs.get("font_size", 10)))
        form.addRow(t("font_size"), self.size)

        self.plan_theme = QComboBox()
        for k, code in (("plan_match", "match"), ("plan_light", "light"), ("plan_dark", "dark")):
            self.plan_theme.addItem(t(k), code)
        self.plan_theme.setCurrentIndex(max(0, self.plan_theme.findData(prefs.get("plan_theme", "match"))))
        form.addRow(t("plan_colors"), self.plan_theme)
        lay.addLayout(form)

        note = QLabel(t("settings_note"))
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(t("ok"))
        buttons.button(QDialogButtonBox.Cancel).setText(t("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._set_accent(prefs.get("accent", ""), apply=False)
        self.theme.currentIndexChanged.connect(self._changed)
        self.font.currentFontChanged.connect(self._changed)
        self.size.valueChanged.connect(self._changed)
        self.plan_theme.currentIndexChanged.connect(self._changed)

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _set_accent(self, color: str, apply: bool = True):
        self.prefs["accent"] = color
        self.accent_btn.setText(color or tr("accent_default", self.lang))
        if color:
            fg = "#000000" if QColor(color).lightness() > 150 else "#ffffff"
            self.accent_btn.setStyleSheet(f"background:{color};color:{fg};border:none;border-radius:6px;padding:6px")
        else:
            self.accent_btn.setStyleSheet("")
        if apply:
            self._changed()

    def _pick_accent(self):
        c = QColorDialog.getColor(QColor(self.prefs.get("accent") or "#2f6fd6"), self)
        if c.isValid():
            self._set_accent(c.name())

    def _load_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("theme_load", self.lang), "", "Theme (*.json)")
        if not path:
            return
        try:
            self.prefs["custom_theme"] = load_theme_file(path)
        except Exception as e:
            QMessageBox.warning(self, tr("error", self.lang), str(e))
            return
        self.theme.setCurrentIndex(self.theme.findData("custom"))
        self._changed()

    def _changed(self, *_):
        self.prefs.update(theme=self.theme.currentData(), font_family=self.font.currentFont().family(),
                          font_size=self.size.value(), plan_theme=self.plan_theme.currentData())
        if self.prefs["theme"] == "custom" and not self.prefs.get("custom_theme"):
            return
        self.preview(dict(self.prefs))

    def reject(self):
        self.preview(dict(self.original))
        super().reject()


def load_prefs(settings) -> dict:
    from .theme import DEFAULTS
    prefs = dict(DEFAULTS)
    for k in PREF_KEYS:
        v = settings.value(k)
        if v not in (None, ""):
            prefs[k] = v
    if isinstance(prefs.get("custom_theme"), str):
        try:
            prefs["custom_theme"] = json.loads(prefs["custom_theme"])
        except ValueError:
            prefs.pop("custom_theme")
    prefs["font_size"] = int(prefs.get("font_size", 10))
    return prefs


def save_prefs(settings, prefs: dict) -> None:
    for k in PREF_KEYS:
        v = prefs.get(k, "")
        settings.setValue(k, json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v)
