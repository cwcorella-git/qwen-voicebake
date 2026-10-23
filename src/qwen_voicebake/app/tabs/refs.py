"""References tab: the designed clip each voice is cloned from, one per tone."""

from __future__ import annotations

import re

import soundfile as sf
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import refs as refs_mod
from ..session import Session

STATUS_LABELS = {
    "missing": "Missing",
    "ok": "Up to date",
    "stale": "Out of date",
    "modified": "Replaced by hand",
    "pinned": "Pinned",
    "pinned-stale": "Pinned, out of date",
}
STATUS_TIPS = {
    "missing": "Not designed yet. The next bake creates it.",
    "ok": "Matches the voice description and tone.",
    "stale": "The voice or tone changed. The next bake designs it again.",
    "modified": "The file differs from the one recorded. It is used as it is.",
    "pinned": "Chosen by hand. Bakes never replace it.",
    "pinned-stale": "Chosen by hand, but the voice or tone changed since. Unpin to redesign it.",
}
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
SEED_RE = re.compile(r"^seed(\d+)$")


def _duration(path) -> str:
    try:
        info = sf.info(str(path))
        return f"{info.frames / info.samplerate:.2f} s"
    except Exception:  # noqa: BLE001
        return ""


class RefsTab(QWidget):
    play_requested = Signal(str)
    candidates_requested = Signal(str, str, int)
    status_message = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._busy = False

        self.voice = QComboBox()
        self.voice.setMinimumWidth(220)
        self.voice.currentTextChanged.connect(self.refresh)
        intro = QLabel(
            "Each tone a voice speaks in gets one designed reference clip. "
            "Lines are cloned from it. Lines with a direction, and vocal sounds, "
            "are designed directly and need no reference."
        )
        intro.setWordWrap(True)

        # Reference table.
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tone", "Status", "Length", "Seed", "Lines"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._ref_selected)
        self.tree.itemDoubleClicked.connect(lambda *_: self._play_ref())
        self.play_ref = QPushButton("Play")
        self.play_ref.clicked.connect(self._play_ref)
        self.pin_button = QPushButton("Pin")
        self.pin_button.setToolTip("A pinned reference is never redesigned by a bake.")
        self.pin_button.clicked.connect(self._toggle_pin)
        ref_buttons = QHBoxLayout()
        ref_buttons.addStretch(1)
        ref_buttons.addWidget(self.play_ref)
        ref_buttons.addWidget(self.pin_button)
        ref_box = QGroupBox("References")
        ref_layout = QVBoxLayout(ref_box)
        ref_layout.addWidget(self.tree, 1)
        ref_layout.addLayout(ref_buttons)

        # Candidates for the selected tone.
        self.count = QSpinBox()
        self.count.setRange(1, 12)
        self.count.setValue(4)
        self.count.setToolTip("How many takes to design, each with a different seed.")
        self.generate = QPushButton("Generate Candidates")
        self.generate.setToolTip(
            "Design several takes of the reference with different seeds, to choose from."
        )
        self.generate.clicked.connect(self._generate)
        self.cands = QTreeWidget()
        self.cands.setHeaderLabels(["Seed", "Length"])
        self.cands.setRootIsDecorated(False)
        self.cands.setAlternatingRowColors(True)
        self.cands.header().setStretchLastSection(True)
        self.cands.currentItemChanged.connect(lambda *_: self._update_enabled())
        self.cands.itemDoubleClicked.connect(lambda *_: self._play_candidate())
        self.play_cand = QPushButton("Play")
        self.play_cand.clicked.connect(self._play_candidate)
        self.use_cand = QPushButton("Use This One")
        self.use_cand.setToolTip("Make this candidate the reference and pin it.")
        self.use_cand.clicked.connect(self._use_candidate)
        gen_row = QHBoxLayout()
        gen_row.addWidget(QLabel("Count:"))
        gen_row.addWidget(self.count)
        gen_row.addWidget(self.generate)
        gen_row.addStretch(1)
        cand_buttons = QHBoxLayout()
        cand_buttons.addStretch(1)
        cand_buttons.addWidget(self.play_cand)
        cand_buttons.addWidget(self.use_cand)
        self.cand_box = QGroupBox("Candidates")
        cand_layout = QVBoxLayout(self.cand_box)
        cand_layout.addLayout(gen_row)
        cand_layout.addWidget(self.cands, 1)
        cand_layout.addLayout(cand_buttons)

        body = QHBoxLayout()
        body.addWidget(ref_box, 3)
        body.addWidget(self.cand_box, 2)
        self.body = QWidget()
        self.body.setLayout(body)
        body.setContentsMargins(0, 0, 0, 0)

        self.empty = QLabel()
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setEnabled(False)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.body)
        self.stack.addWidget(self.empty)

        top = QHBoxLayout()
        top.addWidget(QLabel("Voice:"))
        top.addWidget(self.voice)
        top.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(intro)
        layout.addWidget(self.stack, 1)

        session.voices_changed.connect(self._voices_changed)
        session.lines_changed.connect(self.refresh)
        session.states_changed.connect(self.refresh)
        self._voices_changed()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_enabled()

    # -- data ----------------------------------------------------------------------------

    def _voices_changed(self) -> None:
        keep = self.voice.currentText()
        self.voice.blockSignals(True)
        self.voice.clear()
        self.voice.addItems(list(self.session.voices))
        if keep in self.session.voices:
            self.voice.setCurrentText(keep)
        self.voice.blockSignals(False)
        self.refresh()

    def _selected_tone(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def refresh(self) -> None:
        project = self.session.project
        name = self.voice.currentText()
        voice = self.session.voices.get(name)
        keep = self._selected_tone()
        self.tree.clear()
        if project is None or voice is None:
            self.empty.setText("No voices yet. Add one on the Voices tab.")
            self.stack.setCurrentWidget(self.empty)
            self._refresh_candidates()
            return
        tones = self.session.clone_tones(name)
        if not tones:
            self.empty.setText(f"No lines for '{name}' need a reference.")
            self.stack.setCurrentWidget(self.empty)
            self._refresh_candidates()
            return
        self.stack.setCurrentWidget(self.body)
        lock = refs_mod.load_lock(project)
        counts: dict[str, int] = {}
        for ln in self.session.lines:
            if ln.voice == name:
                counts[ln.tone] = counts.get(ln.tone, 0) + 1
        for tone in tones:
            status = refs_mod.ref_status(project, voice, tone, self.session.tones[tone], lock)
            entry = lock.get(refs_mod.ref_key(name, tone), {})
            path = refs_mod.ref_path(project, name, tone)
            item = QTreeWidgetItem(
                [
                    tone,
                    STATUS_LABELS.get(status, status),
                    _duration(path) if path.is_file() else "",
                    str(entry.get("seed", "")) if status != "missing" else "",
                    str(counts.get(tone, 0)),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, tone)
            item.setData(1, Qt.ItemDataRole.UserRole, status)
            item.setToolTip(1, STATUS_TIPS.get(status, ""))
            for col in (2, 3, 4):
                item.setTextAlignment(col, RIGHT)
            self.tree.addTopLevelItem(item)
            if tone == keep:
                self.tree.setCurrentItem(item)
        if self.tree.currentItem() is None:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        for col in (0, 2, 3, 4):
            self.tree.resizeColumnToContents(col)
            self.tree.setColumnWidth(col, self.tree.columnWidth(col) + 16)
        self._refresh_candidates()

    def _ref_selected(self, *_: object) -> None:
        self._refresh_candidates()

    def _refresh_candidates(self) -> None:
        self.cands.clear()
        tone = self._selected_tone()
        project = self.session.project
        name = self.voice.currentText()
        if project is None or tone is None:
            self.cand_box.setTitle("Candidates")
            self._update_enabled()
            return
        self.cand_box.setTitle(f"Candidates for {tone}")
        folder = refs_mod.candidate_dir(project, name, tone)
        found = []
        if folder.is_dir():
            for p in folder.glob(f"*.{refs_mod.REF_FORMAT}"):
                m = SEED_RE.match(p.stem)
                if m:
                    found.append((int(m.group(1)), p))
        for seed, p in sorted(found):
            item = QTreeWidgetItem([str(seed), _duration(p)])
            item.setData(0, Qt.ItemDataRole.UserRole, seed)
            item.setData(1, Qt.ItemDataRole.UserRole, str(p))
            self.cands.addTopLevelItem(item)
        if found:
            self.cands.setCurrentItem(self.cands.topLevelItem(0))
        else:
            placeholder = QTreeWidgetItem(["None yet", ""])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.cands.addTopLevelItem(placeholder)
        self._update_enabled()

    def _update_enabled(self) -> None:
        item = self.tree.currentItem()
        status = item.data(1, Qt.ItemDataRole.UserRole) if item else None
        writable = not self.session.read_only and not self._busy
        self.play_ref.setEnabled(status not in (None, "missing"))
        self.pin_button.setEnabled(writable and status not in (None, "missing"))
        self.pin_button.setText("Unpin" if status in ("pinned", "pinned-stale") else "Pin")
        self.generate.setEnabled(writable and item is not None)
        self.count.setEnabled(writable and item is not None)
        cand = self.cands.currentItem()
        has_cand = cand is not None and cand.data(0, Qt.ItemDataRole.UserRole) is not None
        self.play_cand.setEnabled(has_cand)
        self.use_cand.setEnabled(has_cand and writable)

    # -- actions -------------------------------------------------------------------------

    def _play_ref(self) -> None:
        tone = self._selected_tone()
        if tone and self.session.project is not None:
            path = refs_mod.ref_path(self.session.project, self.voice.currentText(), tone)
            if path.is_file():
                self.play_requested.emit(str(path))

    def _play_candidate(self) -> None:
        item = self.cands.currentItem()
        if item is not None and item.data(1, Qt.ItemDataRole.UserRole):
            self.play_requested.emit(item.data(1, Qt.ItemDataRole.UserRole))

    def _generate(self) -> None:
        tone = self._selected_tone()
        if tone:
            self.candidates_requested.emit(self.voice.currentText(), tone, self.count.value())

    def _toggle_pin(self) -> None:
        item = self.tree.currentItem()
        tone = self._selected_tone()
        if item is None or tone is None or self.session.project is None:
            return
        pinned = item.data(1, Qt.ItemDataRole.UserRole) in ("pinned", "pinned-stale")
        refs_mod.set_pinned(self.session.project, self.voice.currentText(), tone, not pinned)
        word = "unpinned" if pinned else "pinned"
        self.status_message.emit(f"{self.voice.currentText()}/{tone} {word}.")
        self.session.refresh_states()

    def _use_candidate(self) -> None:
        cand = self.cands.currentItem()
        tone = self._selected_tone()
        project = self.session.project
        if cand is None or tone is None or project is None:
            return
        seed = int(cand.data(0, Qt.ItemDataRole.UserRole))
        name = self.voice.currentText()
        if refs_mod.ref_path(project, name, tone).is_file():
            answer = QMessageBox.question(
                self,
                "Use Candidate",
                f"Replace the reference for {name}/{tone} with the seed {seed} candidate?\n\n"
                "Lines cloned from it will be baked again on the next bake.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.pick(seed)

    def pick(self, seed: int) -> None:
        tone = self._selected_tone()
        project = self.session.project
        assert tone is not None and project is not None
        name = self.voice.currentText()
        if self.session.dirty:
            self.session.save()  # the lock records hashes of the saved voice
        refs_mod.pick_candidate(project, name, tone, seed)
        self.status_message.emit(f"{name}/{tone} now uses seed {seed} and is pinned.")
        self.session.refresh_states()
