"""Bake tab: run the pipeline, follow its progress, and review quality warnings."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

LEVEL_LABELS = {
    "error": "Error",
    "warning": "Warning",
    "hard": "Rejected",
    "soft": "Check",
    "failed": "Failed",
}


class BakeTab(QWidget):
    bake_changed_requested = Signal()
    bake_all_requested = Signal()
    cancel_requested = Signal()
    play_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bake_changed = QPushButton("Bake Changed")
        self.bake_changed.setToolTip("Bake lines that are new, changed or failed (Ctrl+B).")
        self.bake_changed.setDefault(True)
        self.bake_changed.clicked.connect(self.bake_changed_requested)
        self.bake_all = QPushButton("Bake All")
        self.bake_all.setToolTip("Bake every line again, except human takes.")
        self.bake_all.clicked.connect(self.bake_all_requested)
        self.cancel = QPushButton("Cancel")
        self.cancel.setToolTip("Stop after the line being baked now.")
        self.cancel.clicked.connect(self.cancel_requested)
        self.cancel.setEnabled(False)
        self.summary = QLabel()

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("%v of %m")
        self.progress.setTextVisible(False)
        self.stage = QLabel("Ready.")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Bake output appears here.")
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        log_box = QGroupBox("Log")
        QVBoxLayout(log_box).addWidget(self.log)

        self.issues = QTreeWidget()
        self.issues.setHeaderLabels(["Level", "Line", "Details"])
        self.issues.setRootIsDecorated(False)
        self.issues.setAlternatingRowColors(True)
        self.issues.header().setStretchLastSection(True)
        self.issues.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.issues.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.issues.itemDoubleClicked.connect(self._issue_activated)
        self.issues_empty = QLabel("No problems reported.")
        self.issues_empty.setEnabled(False)
        self.issues_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        issues_box = QGroupBox("Problems")
        il = QVBoxLayout(issues_box)
        il.addWidget(self.issues, 1)
        il.addWidget(self.issues_empty, 1)
        self.issues.hide()

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(log_box)
        split.addWidget(issues_box)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)

        buttons = QHBoxLayout()
        buttons.addWidget(self.bake_changed)
        buttons.addWidget(self.bake_all)
        buttons.addWidget(self.cancel)
        buttons.addSpacing(12)
        buttons.addWidget(self.summary, 1)

        prog = QHBoxLayout()
        prog.addWidget(self.progress, 1)
        prog.addSpacing(8)
        prog.addWidget(self.stage)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addLayout(prog)
        layout.addWidget(split, 1)

    # -- state ---------------------------------------------------------------------------

    def set_changed_count(self, n: int | None) -> None:
        if n is None:
            self.summary.setText("")
        elif n == 0:
            self.summary.setText("Every line is up to date.")
        else:
            self.summary.setText(f"{n} line{'s' if n != 1 else ''} to bake.")

    def set_state(self, busy: bool, can_bake: bool) -> None:
        self.bake_changed.setEnabled(can_bake and not busy)
        self.bake_all.setEnabled(can_bake and not busy)
        self.cancel.setEnabled(busy)

    def start_run(self, title: str) -> None:
        self.progress.setRange(0, 0)  # busy indicator until the plan size is known
        self.progress.setTextVisible(False)
        self.stage.setText(title)
        self._append(f"-- {title}")

    def set_progress(self, done: int, total: int) -> None:
        if total <= 0:
            return
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setTextVisible(True)
        self.stage.setText(f"{done} of {total}")

    def finish_run(self, text: str, log: bool = False) -> None:
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(1)
        self.stage.setText(text)
        if log:
            self._append(f"-- {text}")

    def clear_issues(self) -> None:
        self.issues.clear()
        self._issues_visibility()

    def _issues_visibility(self) -> None:
        has = self.issues.topLevelItemCount() > 0
        self.issues.setVisible(has)
        self.issues_empty.setVisible(not has)

    def add_issue(self, level: str, where: str, details: str, path: str = "") -> None:
        item = QTreeWidgetItem([LEVEL_LABELS.get(level, level), where, details])
        item.setToolTip(2, details)
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        self.issues.addTopLevelItem(item)
        self._issues_visibility()

    def _issue_activated(self, item: QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.play_requested.emit(path)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(text)

    # -- events from the worker ------------------------------------------------------------

    def handle_event(self, e: dict[str, Any]) -> None:
        kind = e.get("type")
        if kind == "ref":
            where = f"{e['voice']}/{e['tone']}"
            self._append(f"{where:<28} {'reference':<10} {e.get('duration', 0):6.2f} s")
        elif kind == "warn":
            where = f"{e.get('voice', '')}/{e.get('tone', '')}"
            self._append(f"{where:<28} {'warning':<10} {e.get('msg', '')}")
            self.add_issue("failed" if e.get("failed") else "warning", where, e.get("msg", ""))
        elif kind == "take":
            lid = e["line_id"]
            if e["ok"]:
                note = ""
                if e.get("qa") == "soft":
                    note = "  (check: " + ", ".join(e.get("reasons", [])) + ")"
                    self.add_issue("soft", lid, ", ".join(e.get("reasons", [])), e.get("path", ""))
                self._append(f"{lid:<28} {e['route']:<10} {e['duration']:6.2f} s{note}")
            else:
                self._append(f"{lid:<28} {e['route']:<10} failed: {e.get('error', '')}")
                level = "hard" if e.get("qa") == "hard" else "failed"
                self.add_issue(level, lid, e.get("error", ""))
        elif kind == "info":
            self._append(e.get("msg", ""))
        elif kind == "done":
            s = e.get("summary") or {}
            parts = [
                f"baked {len(s.get('baked', []))}",
                f"failed {len(s.get('failed', []))}",
                f"up to date {len(s.get('up_to_date', []))}",
                f"human {len(s.get('skipped_human', []))}",
            ]
            if s.get("soft"):
                parts.append(f"to check {len(s['soft'])}")
            tail = "cancelled" if s.get("cancelled") else f"{s.get('seconds', 0):.1f} s"
            self._append(f"-- Done: {', '.join(parts)}, {tail}")

    def log_message(self, text: str) -> None:
        self._append(text)
