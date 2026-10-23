import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QStandardPaths, Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from qwen_voicebake.app.window import MainWindow  # noqa: E402
from qwen_voicebake.refs import load_lock  # noqa: E402

STARTER = Path(__file__).resolve().parents[1] / "examples" / "starter"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    QStandardPaths.setTestModeEnabled(True)
    # Never block on a modal question; tests that need an answer patch it themselves.
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)


@pytest.fixture
def starter(tmp_path: Path) -> Path:
    root = tmp_path / "starter"
    shutil.copytree(STARTER, root)
    cfg = root / "voicebake.toml"
    cfg.write_text(cfg.read_text().replace("port = 47811", "port = 0"), encoding="utf-8")
    return root


@pytest.fixture
def window(qtbot, starter):
    win = MainWindow(starter, fake=True)
    qtbot.addWidget(win)
    win.show()
    return win


def _wait_idle(qtbot, win, timeout=30000):
    qtbot.waitUntil(lambda: not win._busy, timeout=timeout)


def test_empty_state(qtbot):
    win = MainWindow(None, fake=True)
    qtbot.addWidget(win)
    assert win.stack.currentIndex() == 0
    assert not win.act_save.isEnabled()
    assert not win.act_bake.isEnabled()


def test_edit_save_bake(qtbot, window, starter):
    win = window
    assert win.stack.currentIndex() == 1
    assert win.windowTitle().startswith("starter")
    assert win.session.changed_count() == 12

    model = win.lines_tab.model
    idx = model.index(0, 5)
    assert model.setData(idx, "Back again? Sit down, the kettle is on.", Qt.ItemDataRole.EditRole)
    assert win.session.dirty and win.act_save.isEnabled()
    win.act_save.trigger()
    assert not win.session.dirty
    saved = json.loads((starter / "lines.json").read_text(encoding="utf-8"))
    assert saved["lines"][0]["text"] == "Back again? Sit down, the kettle is on."

    win.act_bake.trigger()
    assert win._busy
    assert not win.bake_tab.bake_changed.isEnabled() and win.bake_tab.cancel.isEnabled()
    _wait_idle(qtbot, win)
    assert (starter / "voice" / "mechanic" / "mech_greet_01.ogg").is_file()
    assert (starter / "voice" / "manifest.json").is_file()
    assert win.session.changed_count() == 0
    assert set(win.session.states.values()) == {"ok"}
    assert "Done: baked 12" in win.bake_tab.log.toPlainText()
    assert win.bake_tab.bake_changed.isEnabled()


def test_bake_blocked_by_check_errors(qtbot, window, starter):
    win = window
    model = win.lines_tab.model
    model.setData(model.index(0, 2), "no_such_tone", Qt.ItemDataRole.EditRole)
    win.bake_changed()
    assert not win._busy
    assert win.bake_tab.issues.topLevelItemCount() >= 1
    assert "Not started" in win.bake_tab.log.toPlainText()


def test_candidates_and_pick(qtbot, window, starter):
    win = window
    tab = win.refs_tab
    tab.voice.setCurrentText("mechanic")
    assert tab._selected_tone() == "warm"
    tab.count.setValue(2)
    tab.generate.click()
    _wait_idle(qtbot, win)
    seeds = [tab.cands.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(2)]
    assert seeds == [1234, 1235]
    tab.pick(1235)
    entry = load_lock(win.session.project)["mechanic/warm"]
    assert entry["pinned"] is True and entry["seed"] == 1235
    assert tab.tree.currentItem().text(1) == "Pinned"
    assert tab.pin_button.text() == "Unpin"


def test_human_take_toggle(qtbot, window, starter):
    win = window
    win.lines_tab.table.selectRow(0)
    win.lines_tab.human_button.click()
    assert (starter / "voice" / "mechanic" / "mech_greet_01.ogg.human").exists()
    assert win.session.states["mech_greet_01"] == "human"
    assert win.lines_tab.human_button.text() == "Unmark Human Take"
    win.lines_tab.human_button.click()
    assert not (starter / "voice" / "mechanic" / "mech_greet_01.ogg.human").exists()


def test_server_regenerate(qtbot, window, starter):
    win = window
    port = win.server.port
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=5) as r:
        status = json.loads(r.read())
    assert status["project"] == str(starter.resolve())
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/regenerate",
        data=b'{"line_id": "ann_dock_01"}',
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    assert out["ok"] is True and out["rel"] == "announcer/ann_dock_01.ogg"
    assert Path(out["path"]).is_file()
    qtbot.waitUntil(lambda: win.session.states.get("ann_dock_01") == "ok", timeout=10000)


def test_read_only_when_locked(qtbot, starter, monkeypatch):
    state = starter / ".voicebake"
    state.mkdir()
    holder = {"pid": os.getppid(), "owner": "cli", "heartbeat": time.time()}
    (state / "lock").write_text(json.dumps(holder), encoding="utf-8")
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a))
    win = MainWindow(starter, fake=True)
    qtbot.addWidget(win)
    assert shown and win.session.read_only
    assert "read-only" in win.windowTitle()
    assert not win.act_bake.isEnabled() and not win.act_add_voice.isEnabled()
    assert not win.session.lines_editable
    assert win.worker is None and win.server is None


def test_voice_rename_updates_lines(qtbot, window):
    win = window
    assert win.session.rename_voice("clerk", "archivist") is None
    assert "archivist" in win.session.voices and "clerk" not in win.session.voices
    assert {ln.voice for ln in win.session.lines if ln.id.startswith("clerk_")} == {"archivist"}
    assert win.session.rename_voice("archivist", "bad name") is not None


def test_bake_all_asks_first(qtbot, window, starter, monkeypatch):
    win = window
    win.bake_all()  # the autouse patch answers Discard, which is not Yes
    assert not win._busy
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.bake_all()
    _wait_idle(qtbot, win)
    assert "Done: baked 12" in win.bake_tab.log.toPlainText()
