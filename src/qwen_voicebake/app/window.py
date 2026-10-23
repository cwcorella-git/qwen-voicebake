"""Main window: menus, tabs, status bar, and the wiring between session, worker and server."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import ConfigError, find_project_root
from .player import Player
from .session import Session
from .tabs.bake import BakeTab
from .tabs.lines import LinesTab
from .tabs.refs import RefsTab
from .tabs.voices import VoicesTab

APP_NAME = "Voicebake"


class MainWindow(QMainWindow):
    def __init__(self, project_dir: str | Path | None = None, fake: bool = False) -> None:
        super().__init__()
        self.fake = fake
        self.session = Session(self)
        self.player = Player(self)
        self.worker: Any = None
        self.server: Any = None
        self.lock: Any = None
        self._busy = False
        self._job_titles: dict[int, str] = {}
        self._status_lock = threading.Lock()
        self._status: dict[str, Any] = {}

        self.voices_tab = VoicesTab(self.session)
        self.lines_tab = LinesTab(self.session)
        self.refs_tab = RefsTab(self.session)
        self.bake_tab = BakeTab()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.voices_tab, "Voices")
        self.tabs.addTab(self.lines_tab, "Lines")
        self.tabs.addTab(self.refs_tab, "References")
        self.tabs.addTab(self.bake_tab, "Bake")

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_welcome())
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self._build_actions()
        self._build_menus()
        self._build_status_bar()
        self._connect()

        self.resize(1040, 700)
        self.setMinimumSize(760, 520)
        settings = QSettings()
        geometry = settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        if project_dir is not None:
            self.open_project(project_dir)
        self._update_title()
        self._update_actions()

    # -- construction --------------------------------------------------------------------

    def _build_welcome(self) -> QWidget:
        page = QWidget()
        title = QLabel("No project open")
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        title.setFont(font)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text = QLabel(
            "Open a folder that contains voicebake.toml, or create a new project\n"
            "from the starter example to see how voices, lines and tones fit together."
        )
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        open_button = QPushButton("Open Project...")
        open_button.clicked.connect(self.choose_project)
        new_button = QPushButton("New Project...")
        new_button.clicked.connect(self.new_project)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(open_button)
        buttons.addWidget(new_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(text)
        layout.addSpacing(16)
        layout.addLayout(buttons)
        layout.addStretch(2)
        return page

    def _action(self, text: str, slot, shortcut: Any = None, tip: str = "") -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
            act.setToolTip(tip)
        return act

    def _build_actions(self) -> None:
        K = QKeySequence.StandardKey
        self.act_open = self._action("&Open Project...", self.choose_project, K.Open)
        self.act_new = self._action("&New Project...", self.new_project, K.New)
        self.act_save = self._action("&Save", self.save, K.Save)
        self.act_reload = self._action(
            "&Reload", self.reload, "F5", "Read the project files from disk again."
        )
        self.act_quit = self._action("&Quit", self.close, K.Quit)
        self.act_add_voice = self._action("Add &Voice", self._add_voice)
        self.act_add_line = self._action("Add &Line", self._add_line, "Ctrl+L")
        self.act_delete = self._action("&Delete", self._delete)
        self.act_bake = self._action(
            "Bake &Changed", self.bake_changed, "Ctrl+B", "Bake new, changed and failed lines."
        )
        self.act_bake_all = self._action(
            "Bake &All", self.bake_all, "Ctrl+Shift+B", "Bake every line again."
        )
        self.act_check = self._action(
            "C&heck Project", self.check, "Ctrl+K", "Look for mistakes in voices and lines."
        )
        self.act_cancel = self._action(
            "C&ancel", self.cancel, None, "Stop after the line being baked now."
        )
        self.act_docs = self._action("&Documentation", self.open_docs, K.HelpContents)
        self.act_about = self._action("&About Voicebake", self.about)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addActions([self.act_new, self.act_open])
        m.addSeparator()
        m.addActions([self.act_save, self.act_reload])
        m.addSeparator()
        m.addAction(self.act_quit)
        m = mb.addMenu("&Edit")
        m.addActions([self.act_add_voice, self.act_add_line])
        m.addSeparator()
        m.addAction(self.act_delete)
        m = mb.addMenu("&Bake")
        m.addActions([self.act_bake, self.act_bake_all])
        m.addSeparator()
        m.addAction(self.act_check)
        m.addSeparator()
        m.addAction(self.act_cancel)
        m = mb.addMenu("&Help")
        m.addAction(self.act_docs)
        m.addSeparator()
        m.addAction(self.act_about)

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        self.sb_device = QLabel()
        self.sb_model = QLabel()
        self.sb_changed = QLabel()
        self.sb_server = QLabel()
        self.sb_device.setToolTip("Where the speech model runs.")
        self.sb_model.setToolTip("The model loaded right now. Loading happens on first use.")
        self.sb_server.setToolTip(
            "Local address editor plugins use to ask for a line to be baked again."
        )
        for w in (self.sb_changed, self.sb_model, self.sb_device, self.sb_server):
            w.setContentsMargins(8, 0, 8, 0)
            sb.addPermanentWidget(w)
        self._set_engine_labels("", "")

    def _connect(self) -> None:
        s = self.session
        s.dirty_changed.connect(lambda _: (self._update_title(), self._update_actions()))
        s.states_changed.connect(self._states_changed)
        s.voices_changed.connect(self._update_actions)
        s.lines_changed.connect(self._update_actions)
        for tab in (self.lines_tab, self.refs_tab, self.bake_tab):
            tab.play_requested.connect(self.player.play)
        for tab in (self.voices_tab, self.lines_tab, self.refs_tab):
            tab.status_message.connect(self._show_message)
        self.lines_tab.regenerate_requested.connect(self.regenerate)
        self.refs_tab.candidates_requested.connect(self.generate_candidates)
        self.bake_tab.bake_changed_requested.connect(self.bake_changed)
        self.bake_tab.bake_all_requested.connect(self.bake_all)
        self.bake_tab.cancel_requested.connect(self.cancel)
        self.player.error.connect(lambda msg: self._show_message(msg, 8000))
        self.tabs.currentChanged.connect(lambda _: self._update_actions())

    def _show_message(self, text: str, timeout: int = 5000) -> None:
        self.statusBar().showMessage(text, timeout)

    # -- project lifecycle ---------------------------------------------------------------

    def choose_project(self) -> None:
        if not self._confirm_discard():
            return
        start = str(self.session.project.root) if self.session.project else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Open Project", start)
        if folder:
            root = find_project_root(folder)
            if root is None:
                QMessageBox.warning(
                    self,
                    "Open Project",
                    f"There is no voicebake.toml in {folder} or the folders above it.",
                )
                return
            self.open_project(root)

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Choose an Empty Folder for the New Project", str(Path.home())
        )
        if not folder:
            return
        from ..cli import CliError, init_project

        try:
            init_project(Path(folder), "starter")
        except CliError as e:
            QMessageBox.warning(self, "New Project", str(e))
            return
        self.open_project(folder)

    def open_project(self, root: str | Path) -> bool:
        self._close_project()
        try:
            self.session.open(root)
        except (ConfigError, OSError, ValueError, KeyError, AttributeError, ImportError) as e:
            QMessageBox.critical(self, "Open Project", f"Could not open the project:\n\n{e}")
            self.session.close()
            self.stack.setCurrentIndex(0)
            self._update_title()
            self._update_actions()
            return False
        project = self.session.project
        assert project is not None

        from ..lockfile import LockHeld, ProjectLock

        self.session.read_only = False
        self.lock = ProjectLock(project.root, "app")
        try:
            self.lock.acquire()
        except LockHeld as e:
            self.lock = None
            self.session.read_only = True
            holder = e.holder
            QMessageBox.information(
                self,
                "Project in Use",
                f"This project is in use by {holder.get('owner')} "
                f"(process {holder.get('pid')}).\n\n"
                "It opens read-only. Close the other session and reload (F5) to make changes.",
            )
        self.session.voices_changed.emit()
        self.session.lines_changed.emit()

        if not self.session.read_only:
            from .worker import EngineWorker

            self.worker = EngineWorker(project, fake=self.fake)
            self.worker.event.connect(self._on_event)
            self.worker.progress.connect(self.bake_tab.set_progress)
            self.worker.job_started.connect(self._job_started)
            self.worker.job_done.connect(self._job_done)
            self.worker.job_failed.connect(self._job_failed)
            self.worker.model_changed.connect(self._model_changed)
            self.worker.busy_changed.connect(self._set_busy)
            self.worker.start()
            self._start_server()
        else:
            self.sb_server.setText("Server: off")
        self._set_engine_labels("", "")
        self.stack.setCurrentIndex(1)
        QSettings().setValue("project/last", str(project.root))
        self._update_title()
        self._update_actions()
        self._states_changed()
        return True

    def _start_server(self) -> None:
        from .server import lines_from_disk, start_server

        project = self.session.project
        worker = self.worker
        assert project is not None and worker is not None
        self._publish_status()

        def status() -> dict[str, Any]:
            with self._status_lock:
                out = dict(self._status)
            out["busy"] = worker.busy
            out["queued"] = worker.queued()
            return out

        def submit(line_id: str, seed: int | None) -> dict[str, Any]:
            return worker.call("regenerate", {"line_id": line_id, "seed": seed})

        try:
            self.server = start_server(
                project.app.port, status, lambda: lines_from_disk(project), submit
            )
            self.sb_server.setText(f"Server: 127.0.0.1:{self.server.port}")
        except OSError as e:
            self.server = None
            self.sb_server.setText("Server: off")
            self.sb_server.setToolTip(f"Port {project.app.port} could not be used: {e}")

    def _publish_status(self) -> None:
        project = self.session.project
        with self._status_lock:
            self._status = {
                "project": str(project.root) if project else "",
                "model": self.worker.model if self.worker else "",
                "device": self.worker.device if self.worker else "",
            }

    def _close_project(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.worker.stop()
            self.worker = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        if self.lock is not None:
            self.lock.release()
            self.lock = None
        self._busy = False
        self.player.stop()

    def save(self) -> bool:
        if self.session.project is None or self.session.read_only:
            return False
        try:
            self.session.save()
        except OSError as e:
            QMessageBox.critical(self, "Save", f"Could not save:\n\n{e}")
            return False
        self._show_message("Saved.")
        return True

    def reload(self) -> None:
        if self.session.project is None or self._busy:
            return
        if self.session.dirty:
            answer = QMessageBox.question(
                self,
                "Reload",
                "Discard unsaved changes and read the project files again?",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Discard:
                return
        self.open_project(self.session.project.root)
        self._show_message("Reloaded.")

    def _confirm_discard(self) -> bool:
        """Ask about unsaved edits. True means it is fine to go on."""
        if not self.session.dirty:
            return True
        answer = QMessageBox.question(
            self,
            APP_NAME,
            "Save changes to this project before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._busy:
            answer = QMessageBox.question(
                self,
                APP_NAME,
                "A bake is running. Stop it and quit?\n\n"
                "The line being baked now is finished first.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if not self._confirm_discard():
            event.ignore()
            return
        QSettings().setValue("window/geometry", self.saveGeometry())
        self._close_project()
        self.player.close()
        event.accept()

    # -- engine work ---------------------------------------------------------------------

    def _prepare_run(self) -> bool:
        """Save edits and make sure the project is valid before engine work."""
        if self.worker is None or self._busy:
            return False
        if self.session.dirty and not self.save():
            return False
        from ..check import run_check

        errors = [i for i in run_check(self.session.project) if i.level == "error"]
        if errors:
            self.tabs.setCurrentWidget(self.bake_tab)
            self.bake_tab.clear_issues()
            for issue in errors:
                self.bake_tab.add_issue(issue.level, issue.where, issue.msg)
            self.bake_tab.log_message(
                f"-- Not started: {len(errors)} error(s) in the project. See Problems below."
            )
            return False
        return True

    def bake_changed(self) -> None:
        if not self._prepare_run():
            return
        self.tabs.setCurrentWidget(self.bake_tab)
        self.bake_tab.clear_issues()
        self._submit("bake", {"force": False}, "Baking changed lines")

    def bake_all(self) -> None:
        if self.worker is None or self._busy:
            return
        n = sum(1 for s in self.session.states.values() if s != "human")
        answer = QMessageBox.question(
            self,
            "Bake All",
            f"Bake all {n} lines again?\n\nExisting audio files are replaced. "
            "Human takes and pinned references are kept.",
        )
        if answer != QMessageBox.StandardButton.Yes or not self._prepare_run():
            return
        self.tabs.setCurrentWidget(self.bake_tab)
        self.bake_tab.clear_issues()
        self._submit("bake", {"force": True}, "Baking all lines")

    def regenerate(self, line_id: str) -> None:
        if not self._prepare_run():
            return
        self._submit("regenerate", {"line_id": line_id}, f"Regenerating {line_id}")
        self._show_message(f"Regenerating {line_id}...")

    def generate_candidates(self, voice: str, tone: str, n: int) -> None:
        if not self._prepare_run():
            return
        self._submit(
            "candidates",
            {"voice": voice, "tone": tone, "n": n},
            f"Designing {n} candidates for {voice}/{tone}",
        )
        self._show_message(f"Designing {n} candidates for {voice}/{tone}...")

    def _submit(self, kind: str, payload: dict[str, Any], title: str) -> int:
        reply = self.worker.submit(kind, payload)
        self._job_titles[reply] = title
        self._set_busy(True)
        return reply

    def cancel(self) -> None:
        if self.worker is not None and self._busy:
            self.worker.cancel()
            self.bake_tab.stage.setText("Stopping after the current line...")

    def check(self) -> None:
        if self.session.project is None:
            return
        if self.session.dirty and not self.save():
            return
        from ..check import run_check

        issues = run_check(self.session.project)
        self.tabs.setCurrentWidget(self.bake_tab)
        self.bake_tab.clear_issues()
        for issue in issues:
            self.bake_tab.add_issue(issue.level, issue.where, issue.msg)
        errors = sum(1 for i in issues if i.level == "error")
        warnings = len(issues) - errors
        if issues:
            msg = f"-- Check: {errors} error(s), {warnings} warning(s)."
        else:
            msg = "-- Check: no problems found."
        self.bake_tab.log_message(msg)
        self._show_message(msg[3:])

    # -- worker signals ------------------------------------------------------------------

    def _job_started(self, reply: int, kind: str) -> None:
        title = self._job_titles.get(reply, "Regenerating a line for an editor request")
        self.bake_tab.start_run(title)

    def _on_event(self, e: dict[str, Any]) -> None:
        self.bake_tab.handle_event(e)

    def _job_done(self, reply: int, result: dict[str, Any]) -> None:
        self._job_titles.pop(reply, None)
        if "summary" in result:
            s = result["summary"]
            text = (
                "Cancelled."
                if s.get("cancelled")
                else (f"Done: {len(s['baked'])} baked, {len(s['failed'])} failed.")
            )
        elif "paths" in result:
            text = f"{len(result['paths'])} candidates ready."
            self.refs_tab.refresh()
        else:
            text = (
                f"{result.get('line_id')} regenerated."
                if result.get("ok")
                else f"{result.get('line_id')}: {result.get('error')}"
            )
        self.bake_tab.finish_run(text, log="summary" not in result)
        self._show_message(text)
        self.session.refresh_states()

    def _job_failed(self, reply: int, error: str) -> None:
        self._job_titles.pop(reply, None)
        self.bake_tab.log_message(f"-- Stopped: {error}")
        self.bake_tab.finish_run("Stopped with an error.")
        self._show_message(error, 10000)
        self.session.refresh_states()

    def _model_changed(self, model: str, device: str) -> None:
        self._set_engine_labels(model, device)
        self._publish_status()

    def _set_engine_labels(self, model: str, device: str) -> None:
        shown = self.session.project is not None
        self.sb_device.setVisible(shown)
        self.sb_model.setVisible(shown)
        self.sb_server.setVisible(shown)
        if self.fake:
            self.sb_device.setText("Device: none (placeholder audio)")
        else:
            self.sb_device.setText(f"Device: {device}" if device else "Device: not started")
        short = model.rsplit("/", 1)[-1] if model else "none loaded"
        self.sb_model.setText(f"Model: {short}")
        self.sb_model.setToolTip(model or "The model loads on first use.")

    def _set_busy(self, busy: bool) -> None:
        if self.worker is not None and not busy and self.worker.busy:
            return  # still working through the queue
        self._busy = busy
        self._update_actions()

    def _states_changed(self) -> None:
        n = self.session.changed_count() if self.session.project else None
        self.bake_tab.set_changed_count(n)
        if n is None:
            self.sb_changed.setText("")
        else:
            self.sb_changed.setText(f"{n} to bake" if n else "All lines up to date")
        self._update_actions()

    # -- menus and title -----------------------------------------------------------------

    def _update_title(self) -> None:
        project = self.session.project
        if project is None:
            self.setWindowTitle(APP_NAME)
            return
        title = f"{project.root.name}[*] - {APP_NAME}"
        if self.session.read_only:
            title += " (read-only)"
        self.setWindowTitle(title)
        self.setWindowModified(self.session.dirty)

    def _update_actions(self) -> None:
        has = self.session.project is not None
        writable = has and not self.session.read_only
        busy = self._busy
        can_run = writable and self.worker is not None
        self.act_save.setEnabled(writable and self.session.dirty)
        self.act_reload.setEnabled(has and not busy)
        self.act_open.setEnabled(not busy)
        self.act_new.setEnabled(not busy)
        self.act_add_voice.setEnabled(writable)
        self.act_add_line.setEnabled(self.session.lines_editable and bool(self.session.voices))
        current = self.tabs.currentWidget()
        self.act_delete.setEnabled(writable and current in (self.voices_tab, self.lines_tab))
        self.act_bake.setEnabled(can_run and not busy)
        self.act_bake_all.setEnabled(can_run and not busy)
        self.act_check.setEnabled(has)
        self.act_cancel.setEnabled(busy)
        self.bake_tab.set_state(busy, can_run)
        self.lines_tab.set_busy(busy)
        self.refs_tab.set_busy(busy)

    def _add_voice(self) -> None:
        self.tabs.setCurrentWidget(self.voices_tab)
        self.voices_tab.add_voice()

    def _add_line(self) -> None:
        self.tabs.setCurrentWidget(self.lines_tab)
        self.lines_tab.add_line()

    def _delete(self) -> None:
        current = self.tabs.currentWidget()
        if current is self.voices_tab:
            self.voices_tab.remove_voice()
        elif current is self.lines_tab:
            self.lines_tab.delete_lines()

    def open_docs(self) -> None:
        candidates = [Path(__file__).resolve().parents[3] / "README.md"]
        if self.session.project is not None:
            candidates.append(self.session.project.root / "README.md")
        for path in candidates:
            if path.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                return
        QMessageBox.information(
            self,
            "Documentation",
            "The README and the docs folder of the qwen-voicebake source describe "
            "every setting and command.",
        )

    def about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>qwen-voicebake {__version__}</b><p>Bakes game dialogue into audio files "
            "with Qwen3-TTS.</p><p>MIT License.</p>",
        )


def run_app(app: QApplication, project_dir: str | Path | None, fake: bool) -> int:
    win = MainWindow(project_dir, fake=fake)
    win.show()
    return app.exec()
