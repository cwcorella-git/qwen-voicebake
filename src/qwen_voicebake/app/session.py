"""The open project as the app sees it: voices, lines and tones in memory, plus save/reload."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..config import Project, load_project
from ..ledger import HUMAN_SUFFIX, Ledger, take_rel
from ..lines_io import csv_to_json, lines_source, load_lines, save_lines_json
from ..planner import plan, route_for
from ..schema import ID_RE, Line, Voice, load_voices, save_voices
from ..tones import load_project_tones


class Session(QObject):
    """Holds one project. Edits happen here; tabs listen to the signals."""

    voices_changed = Signal()
    lines_changed = Signal()
    states_changed = Signal()
    dirty_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project: Project | None = None
        self.voices: dict[str, Voice] = {}
        self.lines: list[Line] = []
        self.tones: dict[str, str] = {}
        self.source = "json"
        self.read_only = False
        self.states: dict[str, str] = {}
        self._dirty = False

    # -- loading and saving ---------------------------------------------------------

    def open(self, root: str | Path) -> None:
        """Load a project. Raises on unreadable files; nothing changes in that case."""
        project = load_project(root)
        voices = load_voices(project.paths.voices) if project.paths.voices.is_file() else {}
        tones = load_project_tones(project)
        source = lines_source(project)
        if source == "json" and not project.paths.lines.is_file():
            lines: list[Line] = []
        else:
            lines = load_lines(project)
        self.project, self.voices, self.tones, self.lines = project, voices, tones, lines
        self.source = source
        self._set_dirty(False)
        self.voices_changed.emit()
        self.lines_changed.emit()
        self.refresh_states()

    def reload(self) -> None:
        if self.project is not None:
            self.open(self.project.root)

    def close(self) -> None:
        self.project = None
        self.voices, self.lines, self.tones, self.states = {}, [], {}, {}
        self._set_dirty(False)
        self.voices_changed.emit()
        self.lines_changed.emit()
        self.states_changed.emit()

    def save(self) -> None:
        if self.project is None or self.read_only:
            return
        save_voices(self.project.paths.voices, self.voices)
        if self.lines_editable:
            save_lines_json(self.project.paths.lines, self.lines)
        self._set_dirty(False)
        self.refresh_states()

    @property
    def dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, value: bool) -> None:
        if value != self._dirty:
            self._dirty = value
            self.dirty_changed.emit(value)

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    @property
    def lines_editable(self) -> bool:
        return self.source == "json" and not self.read_only

    # -- line states ------------------------------------------------------------------

    def refresh_states(self) -> None:
        """Recompute each line's take state from the saved ledger and the files on disk."""
        self.states = {}
        if self.project is None:
            self.states_changed.emit()
            return
        valid = [ln for ln in self.lines if ln.voice in self.voices and ln.tone in self.tones]
        try:
            ledger = Ledger.for_root(self.project.root)
            p = plan(self.project, self.voices, valid, self.tones, ledger)
        except (OSError, ValueError):
            p = None
        if p is not None:
            for job in p.jobs:
                self.states[job.line.id] = job.state
            for lid in p.up_to_date:
                self.states[lid] = "ok"
            for lid in p.skipped_human:
                self.states[lid] = "human"
        for ln in self.lines:
            self.states.setdefault(ln.id, "invalid")
        self.states_changed.emit()

    def changed_count(self) -> int:
        return sum(1 for s in self.states.values() if s in ("new", "stale", "failed"))

    def take_path(self, line: Line) -> Path:
        assert self.project is not None
        return self.project.paths.out / take_rel(line, self.project.paths.format)

    def human_marker(self, line: Line) -> Path:
        return Path(str(self.take_path(line)) + HUMAN_SUFFIX)

    def set_human(self, line: Line, human: bool) -> None:
        marker = self.human_marker(line)
        if human:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
        elif marker.exists():
            marker.unlink()
        self.refresh_states()

    def clone_tones(self, voice: str) -> list[str]:
        """Tones that need a reference clip for this voice, in first-use order."""
        seen: dict[str, None] = {}
        for ln in self.lines:
            if ln.voice == voice and route_for(ln) == "clone" and ln.tone in self.tones:
                seen.setdefault(ln.tone, None)
        return list(seen)

    # -- voice edits ------------------------------------------------------------------

    def new_voice_name(self) -> str:
        n = 1
        while f"voice{n}" in self.voices:
            n += 1
        return f"voice{n}"

    def add_voice(self) -> str:
        name = self.new_voice_name()
        self.voices[name] = Voice(name=name, instruct="", ref_text="")
        self.mark_dirty()
        self.voices_changed.emit()
        return name

    def update_voice(self, name: str, **fields) -> None:
        self.voices[name] = replace(self.voices[name], **fields)
        self.mark_dirty()

    def rename_voice(self, old: str, new: str) -> str | None:
        """Rename a voice and the lines that use it. Returns an error message or None."""
        if new == old:
            return None
        if not ID_RE.match(new):
            return "A voice name may only contain letters, digits, '_', '.' and '-'."
        if new in self.voices:
            return f"There is already a voice named '{new}'."
        if not self.lines_editable and any(ln.voice == old for ln in self.lines):
            return "Lines come from a read-only source, so voices they use cannot be renamed."
        self.voices = {
            (new if k == old else k): (replace(v, name=new) if k == old else v)
            for k, v in self.voices.items()
        }
        self.lines = [replace(ln, voice=new) if ln.voice == old else ln for ln in self.lines]
        self.mark_dirty()
        self.voices_changed.emit()
        self.lines_changed.emit()
        return None

    def lines_using(self, voice: str) -> int:
        return sum(1 for ln in self.lines if ln.voice == voice)

    def remove_voice(self, name: str) -> None:
        self.voices.pop(name, None)
        self.mark_dirty()
        self.voices_changed.emit()

    # -- line edits -------------------------------------------------------------------

    def add_line(self, after: int | None = None) -> int:
        n = len(self.lines) + 1
        ids = {ln.id for ln in self.lines}
        while f"line_{n:03d}" in ids:
            n += 1
        voice = next(iter(self.voices), "")
        if after is not None and 0 <= after < len(self.lines):
            voice = self.lines[after].voice
        line = Line(id=f"line_{n:03d}", voice=voice, tone="neutral", text="")
        row = len(self.lines) if after is None else after + 1
        self.lines.insert(row, line)
        self.mark_dirty()
        self.lines_changed.emit()
        return row

    def set_line(self, row: int, line: Line) -> None:
        self.lines[row] = line
        self.mark_dirty()

    def remove_lines(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            del self.lines[row]
        self.mark_dirty()
        self.lines_changed.emit()

    def convert_csv_to_json(self) -> Path:
        """Write lines.json beside the CSV and point voicebake.toml at it."""
        assert self.project is not None
        csv_path = self.project.paths.lines
        json_path = csv_path.with_suffix(".json")
        if json_path.exists():
            raise FileExistsError(f"{json_path.name} already exists")
        cfg = self.project.root / "voicebake.toml"
        text = cfg.read_text(encoding="utf-8")
        pattern = re.compile(r'^(\s*lines\s*=\s*")([^"]*\.csv)(")', re.MULTILINE)
        if not pattern.search(text):
            raise ValueError("could not find the lines setting in voicebake.toml")
        csv_to_json(csv_path, json_path)
        from .._atomic import atomic_write_text

        rel = Path(pattern.search(text).group(2)).with_suffix(".json").as_posix()  # type: ignore[union-attr]
        atomic_write_text(cfg, pattern.sub(lambda m: m.group(1) + rel + m.group(3), text, count=1))
        self.open(self.project.root)
        return json_path
