"""Voices tab: a list of voices and a form for the selected one."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..session import Session

LANGUAGES = [
    "English",
    "Chinese",
    "Japanese",
    "Korean",
    "German",
    "French",
    "Russian",
    "Portuguese",
    "Spanish",
    "Italian",
]


class VoicesTab(QWidget):
    status_message = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._loading = False
        self._current: str | None = None

        # Left: list and its buttons.
        self.list = QListWidget()
        self.list.setMinimumWidth(180)
        self.list.currentTextChanged.connect(self._select)
        self.add_button = QPushButton("Add Voice")
        self.add_button.clicked.connect(self.add_voice)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_voice)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        left = QVBoxLayout()
        left.addWidget(QLabel("Voices"))
        left.addWidget(self.list, 1)
        left.addLayout(buttons)

        # Right: the form, or an empty-state page.
        self.name = QLineEdit()
        self.name.setToolTip(
            "Used in line files and as the output folder name. "
            "Letters, digits, '_', '.' and '-' only."
        )
        self.name.editingFinished.connect(self._rename)
        self.instruct = QPlainTextEdit()
        self.instruct.setPlaceholderText("Describe the speaker: age, voice quality, manner, role.")
        self.instruct.setToolTip(
            "The voice description given to the design model. Tones are appended to it."
        )
        self.instruct.setFixedHeight(self.instruct.fontMetrics().lineSpacing() * 6 + 16)
        self.instruct.textChanged.connect(lambda: self._edit(instruct=self.instruct.toPlainText()))
        self.ref_text = QPlainTextEdit()
        self.ref_text.setPlaceholderText("One natural sentence this character might say.")
        self.ref_text.setToolTip(
            "Spoken in every reference clip for this voice. A full, ordinary sentence works best."
        )
        self.ref_text.setFixedHeight(self.ref_text.fontMetrics().lineSpacing() * 3 + 16)
        self.ref_text.textChanged.connect(lambda: self._edit(ref_text=self.ref_text.toPlainText()))
        self.seed = QSpinBox()
        self.seed.setRange(0, 2**31 - 1)
        self.seed.setToolTip("Random seed for this voice. Change it to get a different take.")
        self.seed.valueChanged.connect(lambda v: self._edit(seed=int(v)))
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setDecimals(2)
        self.temperature.setToolTip("Sampling temperature. Lower is steadier, higher is livelier.")
        self.temperature.valueChanged.connect(self._temperature_changed)
        self.language = QComboBox()
        self.language.currentIndexChanged.connect(self._language_changed)
        for w in (self.seed, self.temperature, self.language):
            w.setMinimumWidth(220)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.addRow("Name:", self.name)
        form.addRow("Description:", self.instruct)
        form.addRow("Reference text:", self.ref_text)
        form.addRow("Seed:", self._left(self.seed))
        form.addRow("Temperature:", self._left(self.temperature))
        form.addRow("Language:", self._left(self.language))
        self.form_box = QGroupBox("Voice")
        box_layout = QVBoxLayout(self.form_box)
        box_layout.addLayout(form)
        box_layout.addStretch(1)

        self.empty = QLabel("No voices yet.\nAdd a voice to describe a character's speaking voice.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setEnabled(False)
        self.right = QStackedWidget()
        self.right.addWidget(self.form_box)
        self.right.addWidget(self.empty)

        layout = QHBoxLayout(self)
        layout.addLayout(left, 0)
        layout.addWidget(self.right, 1)

        session.voices_changed.connect(self.reload)
        self.reload()

    @staticmethod
    def _left(widget: QWidget) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        lay.addStretch(1)
        return box

    # -- data ----------------------------------------------------------------------------

    def reload(self) -> None:
        keep = self._current
        self._loading = True
        self.list.clear()
        self.list.addItems(list(self.session.voices))
        self._loading = False
        project = self.session.project
        self._loading = True
        self.language.clear()
        default_lang = project.engine.language if project else "English"
        self.language.addItem(f"Project default ({default_lang})", None)
        for lang in LANGUAGES:
            self.language.addItem(lang, lang)
        default_temp = project.engine.temperature if project else 0.5
        self.temperature.setSpecialValueText(f"Project default ({default_temp:g})")
        self._loading = False
        names = list(self.session.voices)
        if keep in self.session.voices:
            self.list.setCurrentRow(names.index(keep))
        elif names:
            self.list.setCurrentRow(0)
        else:
            self._select("")
        self._update_enabled()

    def _update_enabled(self) -> None:
        editable = self.session.project is not None and not self.session.read_only
        has = bool(self.session.voices)
        self.right.setCurrentWidget(self.form_box if has else self.empty)
        self.add_button.setEnabled(editable)
        self.remove_button.setEnabled(editable and self._current is not None)
        self.form_box.setEnabled(editable)

    def _select(self, name: str) -> None:
        if self._loading:
            return
        voice = self.session.voices.get(name)
        self._current = name if voice else None
        self._loading = True
        if voice is None:
            self.name.clear()
            self.instruct.clear()
            self.ref_text.clear()
            self.seed.setValue(0)
            self.temperature.setValue(0.0)
            self.language.setCurrentIndex(0)
        else:
            self.name.setText(voice.name)
            self.instruct.setPlainText(voice.instruct)
            self.ref_text.setPlainText(voice.ref_text)
            self.seed.setValue(voice.seed)
            self.temperature.setValue(voice.temperature or 0.0)
            idx = self.language.findData(voice.language) if voice.language else 0
            self.language.setCurrentIndex(max(idx, 0))
        self._loading = False
        self._update_enabled()

    def _edit(self, **fields) -> None:
        if self._loading or self._current is None:
            return
        self.session.update_voice(self._current, **fields)

    def _temperature_changed(self, value: float) -> None:
        self._edit(temperature=None if value <= 0.0 else round(float(value), 2))

    def _language_changed(self, index: int) -> None:
        self._edit(language=self.language.itemData(index))

    def _rename(self) -> None:
        if self._loading or self._current is None:
            return
        new = self.name.text().strip()
        error = self.session.rename_voice(self._current, new)
        if error:
            QMessageBox.warning(self, "Rename Voice", error)
            self.name.setText(self._current)
            return
        self._current = new
        self.reload()

    # -- actions -------------------------------------------------------------------------

    def add_voice(self) -> None:
        name = self.session.add_voice()
        self._current = name
        self.reload()
        self.name.setFocus()
        self.name.selectAll()

    def remove_voice(self) -> None:
        name = self._current
        if name is None:
            return
        used = self.session.lines_using(name)
        if used:
            QMessageBox.information(
                self,
                "Remove Voice",
                f"'{name}' is used by {used} line(s). "
                "Move or delete those lines before removing the voice.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Remove Voice",
            f"Remove the voice '{name}'?\n\nAudio already baked for it is not deleted.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._current = None
        self.session.remove_voice(name)
