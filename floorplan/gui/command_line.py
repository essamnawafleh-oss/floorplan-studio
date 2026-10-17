"""AutoCAD-like command line: history, current prompt, input, status toggles."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class CommandInput(QLineEdit):
    submitted = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history, self.hpos = [], 0

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter) or (k == Qt.Key_Space and not getattr(self, "allow_space", False)):
            text = self.text()
            if text.strip():
                self.history.append(text)
                self.hpos = len(self.history)
            self.clear()
            self.submitted.emit(text)
            return
        if k == Qt.Key_Escape:
            self.clear()
            self.cancelled.emit()
            return
        if k == Qt.Key_Up and self.history:
            self.hpos = max(0, self.hpos - 1)
            self.setText(self.history[self.hpos])
            return
        if k == Qt.Key_Down and self.history:
            self.hpos = min(len(self.history), self.hpos + 1)
            self.setText(self.history[self.hpos] if self.hpos < len(self.history) else "")
            return
        super().keyPressEvent(e)


class CommandLine(QWidget):
    def __init__(self, cad, parent=None):
        super().__init__(parent)
        self.cad = cad
        self.setLayoutDirection(Qt.LeftToRight)       # commands are Latin, like AutoCAD
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(2)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.setFont(mono)
        self.history.setMaximumHeight(52)
        self.history.setMaximumBlockCount(200)
        lay.addWidget(self.history)
        row = QHBoxLayout()
        self.prompt = QLabel()
        self.prompt.setFont(mono)
        self.prompt.setLayoutDirection(Qt.RightToLeft if cad.lang == "ar" else Qt.LeftToRight)
        row.addWidget(self.prompt)
        self.input = CommandInput()
        self.input.setFont(mono)
        self.input.setPlaceholderText("L · PL · REC · C · A · T · DIM · O · TR · EX · X · M · CO · RO · SC · MI · E")
        self.input.submitted.connect(self._submit)
        self.input.cancelled.connect(lambda: cad.cancel())
        row.addWidget(self.input, 1)
        self.toggles = {}
        for key, label, tip in (("osnap", "OSNAP", "F3"), ("ortho", "ORTHO", "F8"), ("grid", "GRID", "F9")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(getattr(cad, key))
            b.setToolTip(tip)
            b.setMinimumWidth(78)
            b.toggled.connect(lambda on, k=key: setattr(cad, k, on))
            row.addWidget(b)
            self.toggles[key] = b
        lay.addLayout(row)
        cad.promptChanged.connect(self.set_prompt)
        cad.log.connect(self.history.appendPlainText)
        self.set_prompt(cad.prompt_text())

    def _submit(self, text):
        self.cad.submit(text)
        cmd = self.cad.cmd
        self.input.allow_space = cmd is not None and type(cmd).__name__ == "Text" and cmd.step == "text"

    def set_prompt(self, text):
        self.prompt.setText(text + "  ›")
        cmd = self.cad.cmd
        self.input.allow_space = cmd is not None and type(cmd).__name__ == "Text" and getattr(cmd, "step", "") == "text"

    def sync_toggles(self):
        for k, b in self.toggles.items():
            b.blockSignals(True)
            b.setChecked(getattr(self.cad, k))
            b.blockSignals(False)

    def type_char(self, text):
        self.input.setFocus()
        self.input.insert(text)
