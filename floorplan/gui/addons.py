"""Python add-ons (like Blender add-ons).

An add-on is a .py file in the user add-ons folder:

    ADDON = {"name": "My tool", "description": "...", "version": "1.0"}

    def register(api):            # called when the add-on is enabled
        api.add_action("Do it", lambda: run(api))

    def unregister(api):          # optional
        ...

`api` is AddonAPI below. Add-ons run with full Python rights, so only enable
code you wrote or trust.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import sys
import traceback

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QAction, QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from ..paths import user_dir
from .strings import tr

TEMPLATE = '''"""My tool for Floor Plan Studio."""

ADDON = {"name": "My tool", "description": "Shows the area of every room", "version": "1.0"}


def register(api):
    api.add_action("Room areas", lambda: show_areas(api))


def show_areas(api):
    plan = api.plan
    if plan is None:
        return
    lines = [f"{r.spec.name_en}: {r.net.area:.2f} m2" for r in plan.rooms]
    api.message("\\n".join(lines))
'''


class AddonAPI:
    """What an add-on can use. `api.plan` is the live plan (edit it through
    api.edit so changes can be undone)."""

    def __init__(self, window, addon_name: str, manager=None, key: str = ""):
        self._w, self.name = window, addon_name
        self._manager, self._key = manager, key or addon_name

    # data
    @property
    def plan(self):
        return self._w.editor.plan

    @property
    def library(self):
        return self._w.library

    @property
    def lang(self):
        return self._w.lang

    def config(self) -> dict:
        return self._w.panel.get_config()

    def set_config(self, cfg: dict, regenerate: bool = True):
        self._w.panel.set_config(cfg)
        if regenerate:
            self._w.regenerate()

    # changes
    def edit(self, fn):
        """Run fn(plan) as one undoable change (switches on edit mode)."""
        self._w.set_edit_mode(True)
        self._w.editor.apply(fn)

    def set_plan(self, plan):
        self._w.load_edited_plan(plan)

    def regenerate(self, seed: int | None = None):
        if seed is not None:
            self._w.panel.seed.setValue(seed)
        self._w.regenerate()

    def quantities(self, options: dict | None = None) -> dict:
        from ..quantities import compute
        return compute(self.plan, options)

    def export(self, kind: str, path: str):
        self._w.write_file(kind, path)

    # UI
    def add_action(self, label: str, callback, tooltip: str = ""):
        a = QAction(label, self._w)
        a.setToolTip(tooltip)

        def run():
            try:
                callback()
            except Exception:
                self.error(traceback.format_exc())
        a.triggered.connect(run)
        (self._manager or self._w.addons).register_action(self._key, a)
        return a

    def message(self, text: str, title: str = ""):
        QMessageBox.information(self._w, title or self.name, str(text))

    def error(self, text: str):
        QMessageBox.warning(self._w, self.name, str(text))

    def ask_text(self, label: str, default: str = "") -> str | None:
        v, ok = QInputDialog.getText(self._w, self.name, label, text=default)
        return v if ok else None

    def ask_number(self, label: str, default: float = 0.0, lo: float = -1e9, hi: float = 1e9, decimals: int = 2):
        v, ok = QInputDialog.getDouble(self._w, self.name, label, default, lo, hi, decimals)
        return v if ok else None

    def save_file(self, caption: str = "", filter: str = "All (*)") -> str | None:
        path, _ = QFileDialog.getSaveFileName(self._w, caption or self.name, "", filter)
        return path or None

    def status(self, text: str):
        self._w.status.setText(str(text))


def read_meta(path: str) -> dict:
    """ADDON = {...} without running the file."""
    meta = {"name": os.path.splitext(os.path.basename(path))[0], "description": "", "version": ""}
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "ADDON" for t in node.targets):
                meta.update(ast.literal_eval(node.value))
    except Exception as e:
        meta["error"] = str(e)
    return meta


class AddonManager:
    def __init__(self, window, settings, examples_dir: str | None = None):
        self.w, self.settings = window, settings
        self.dir = user_dir("addons")
        self.loaded: dict[str, object] = {}
        self.actions: dict[str, list] = {}
        self.menu = None
        if examples_dir and os.path.isdir(examples_dir) and not self.settings.value("addons_seeded"):
            for fn in os.listdir(examples_dir):          # first run: copy the example add-ons (disabled)
                if fn.endswith(".py") and not os.path.exists(os.path.join(self.dir, fn)):
                    shutil.copy(os.path.join(examples_dir, fn), self.dir)
            self.settings.setValue("addons_seeded", "1")

    def files(self) -> list[str]:
        return sorted(os.path.join(self.dir, f) for f in os.listdir(self.dir) if f.endswith(".py"))

    def enabled(self) -> list[str]:
        try:
            return json.loads(self.settings.value("addons_enabled") or "[]")
        except ValueError:
            return []

    def _save_enabled(self, names):
        self.settings.setValue("addons_enabled", json.dumps(sorted(set(names))))

    def key(self, path: str) -> str:
        return os.path.splitext(os.path.basename(path))[0]

    def load_all(self):
        for path in self.files():
            if self.key(path) in self.enabled():
                self.load(path, quiet=True)

    def load(self, path: str, quiet: bool = False) -> str | None:
        """Import + register. Returns an error text or None."""
        key = self.key(path)
        self.unload(key)
        try:
            spec = importlib.util.spec_from_file_location(f"fps_addon_{key}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            if not hasattr(mod, "register"):
                raise AttributeError("register(api) is missing")
            api = AddonAPI(self.w, getattr(mod, "ADDON", {}).get("name", key), self, key)
            mod.__fps_api__ = api
            mod.register(api)
            self.loaded[key] = mod
            return None
        except Exception:
            err = traceback.format_exc()
            self.unload(key)
            if not quiet:
                QMessageBox.warning(self.w, key, err)
            return err

    def unload(self, key: str):
        mod = self.loaded.pop(key, None)
        if mod is not None and hasattr(mod, "unregister"):
            try:
                mod.unregister(mod.__fps_api__)
            except Exception:
                traceback.print_exc() if sys.stderr else None
        for a in self.actions.pop(key, []):
            if self.menu:
                self.menu.removeAction(a)
        sys.modules.pop(f"fps_addon_{key}", None)

    def register_action(self, key: str, action):
        self.actions.setdefault(key, []).append(action)
        if self.menu:
            self.menu.addAction(action)

    def set_enabled(self, path: str, on: bool):
        key = self.key(path)
        names = set(self.enabled())
        if on:
            err = self.load(path)
            if err:
                return err
            names.add(key)
        else:
            self.unload(key)
            names.discard(key)
        self._save_enabled(names)
        return None

    def attach_menu(self, menu):
        """(Re)build the Tools menu after the window was rebuilt."""
        self.menu = menu
        for acts in self.actions.values():
            for a in acts:
                menu.addAction(a)


class PythonHighlighter(QSyntaxHighlighter):
    KEYWORDS = ("and as assert break class continue def del elif else except False finally for from global if "
                "import in is lambda None nonlocal not or pass raise return True try while with yield").split()

    def __init__(self, doc, dark: bool):
        super().__init__(doc)
        def fmt(color, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            f.setFontItalic(italic)
            return f
        kw, st, cm, num = ("#c792ea", "#c3e88d", "#7f8c98", "#f78c6c") if dark else ("#7c3aed", "#15803d", "#6b7280", "#c2410c")
        self.rules = [(QRegularExpression(r"\b(" + "|".join(self.KEYWORDS) + r")\b"), fmt(kw, True)),
                      (QRegularExpression(r"\b[0-9]+(\.[0-9]+)?\b"), fmt(num)),
                      (QRegularExpression(r"(\"[^\"\n]*\"|'[^'\n]*')"), fmt(st)),
                      (QRegularExpression(r"#[^\n]*"), fmt(cm, italic=True))]

    def highlightBlock(self, text):
        for rx, f in self.rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), f)


class ScriptEditor(QDialog):
    def __init__(self, manager: AddonManager, path: str | None, lang: str, dark: bool, parent=None):
        super().__init__(parent)
        self.m, self.path, self.lang = manager, path, lang
        t = lambda k: tr(k, lang)
        self.setWindowTitle(t("addon_editor"))
        self.resize(900, 680)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("addon_file")))
        self.name = QLineEdit(manager.key(path) if path else "my_tool")
        row.addWidget(self.name, 1)
        lay.addLayout(row)
        self.code = QPlainTextEdit()
        self.code.setLayoutDirection(Qt.LeftToRight)
        self.code.setLineWrapMode(QPlainTextEdit.NoWrap)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(11)
        self.code.setFont(f)
        self.code.setTabStopDistance(4 * self.code.fontMetrics().horizontalAdvance(" "))
        if path:
            with open(path, encoding="utf-8") as fh:
                self.code.setPlainText(fh.read())
        else:
            self.code.setPlainText(TEMPLATE)
        self.hl = PythonHighlighter(self.code.document(), dark)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumHeight(140)
        self.out.setFont(f)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.code)
        split.addWidget(self.out)
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        for label, slot in ((t("addon_check"), self.check), (t("save_file"), self.save), (t("addon_save_enable"), self.save_enable),
                            (t("close"), self.reject)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

    def _target(self) -> str:
        name = re.sub(r"[^A-Za-z0-9_]+", "_", self.name.text().strip()) or "my_tool"
        return os.path.join(self.m.dir, name + ".py")

    def check(self) -> bool:
        try:
            compile(self.code.toPlainText(), self._target(), "exec")
        except SyntaxError as e:
            self.out.setPlainText(f"SyntaxError line {e.lineno}: {e.msg}")
            return False
        self.out.setPlainText("✓ OK")
        return True

    def save(self) -> str | None:
        if not self.check():
            return None
        target = self._target()
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(self.code.toPlainText())
        if self.path and os.path.abspath(self.path) != os.path.abspath(target) and os.path.exists(self.path):
            self.m.set_enabled(self.path, False)
            os.remove(self.path)
        self.path = target
        self.out.appendPlainText(f"{tr('saved', self.lang)}: {target}")
        return target

    def save_enable(self):
        path = self.save()
        if path:
            err = self.m.set_enabled(path, True)
            self.out.appendPlainText(err or "✓ " + tr("addon_enabled", self.lang))


class AddonsDialog(QDialog):
    def __init__(self, manager: AddonManager, lang: str, dark: bool, parent=None):
        super().__init__(parent)
        self.m, self.lang, self.dark = manager, lang, dark
        t = lambda k: tr(k, lang)
        self.setWindowTitle(t("addons"))
        self.resize(720, 480)
        lay = QVBoxLayout(self)
        warn = QLabel(t("addon_warning"))
        warn.setWordWrap(True)
        warn.setObjectName("muted")
        lay.addWidget(warn)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._toggled)
        self.list.itemDoubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, slot in ((t("addon_new"), self.new), (t("addon_edit"), self.edit), (t("addon_import"), self.import_file),
                            (t("delete"), self.delete), (t("addon_folder"), self.open_folder), (t("close"), self.accept)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.list.blockSignals(True)
        self.list.clear()
        enabled = set(self.m.enabled())
        for path in self.m.files():
            meta = read_meta(path)
            it = QListWidgetItem(f"{meta.get('name')}   {meta.get('version', '')}\n{meta.get('description', '')}")
            it.setData(Qt.UserRole, path)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if self.m.key(path) in enabled else Qt.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _toggled(self, it):
        err = self.m.set_enabled(it.data(Qt.UserRole), it.checkState() == Qt.Checked)
        if err:
            self.refresh()

    def _current(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def new(self):
        ScriptEditor(self.m, None, self.lang, self.dark, self).exec()
        self.refresh()

    def edit(self):
        path = self._current()
        if path:
            ScriptEditor(self.m, path, self.lang, self.dark, self).exec()
            self.refresh()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("addon_import", self.lang), "", "Python (*.py)")
        if path:
            shutil.copy(path, self.m.dir)
            self.refresh()

    def delete(self):
        path = self._current()
        if path and QMessageBox.question(self, tr("delete", self.lang), os.path.basename(path)) == QMessageBox.Yes:
            self.m.set_enabled(path, False)
            os.remove(path)
            self.refresh()

    def open_folder(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.m.dir))
