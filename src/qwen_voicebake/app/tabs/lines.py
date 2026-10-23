"""Lines tab: an editable table of every line and its take state."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ...schema import KINDS
from ..session import Session

COLUMNS = ["ID", "Voice", "Tone", "Kind", "Direction", "Text", "State"]
FIELDS = ["id", "voice", "tone", "kind", "direction", "text", None]
STATE_LABELS = {
    "new": "Not baked",
    "stale": "Changed",
    "failed": "Failed",
    "ok": "Up to date",
    "human": "Human take",
    "invalid": "Invalid",
}
STATE_TIPS = {
    "new": "No audio yet. Bake to create it.",
    "stale": "The line or its voice changed since it was baked.",
    "failed": "The last attempt failed. See the Bake tab for the reason.",
    "ok": "The audio file matches the current line.",
    "human": "A recorded take replaces this line. Bakes leave it alone.",
    "invalid": "Unknown voice or tone. Fix it before baking.",
}
COL_STATE = 6
COL_TEXT = 5
TIP_COLUMNS = (0, 2, 4, COL_TEXT)  # columns whose full text may be cut off

Index = QModelIndex | QPersistentModelIndex


class LinesModel(QAbstractTableModel):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        session.lines_changed.connect(self._reset)
        session.states_changed.connect(self._states)

    def _reset(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    def _states(self) -> None:
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, COL_STATE), self.index(self.rowCount() - 1, COL_STATE)
            )

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self.session.lines)

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0) -> Any:  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        line = self.session.lines[index.row()]
        col = index.column()
        if col == COL_STATE:
            state = self.session.states.get(line.id, "")
            if role == Qt.ItemDataRole.DisplayRole:
                return STATE_LABELS.get(state, state)
            if role == Qt.ItemDataRole.ToolTipRole:
                return STATE_TIPS.get(state)
            if role == Qt.ItemDataRole.UserRole:
                return state
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return getattr(line, FIELDS[col])
        if role == Qt.ItemDataRole.ToolTipRole and col in TIP_COLUMNS:
            return getattr(line, FIELDS[col]) or None
        return None

    def flags(self, index: Index) -> Qt.ItemFlag:
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() != COL_STATE and self.session.lines_editable:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, index: Index, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        field = FIELDS[index.column()]
        if field is None:
            return False
        line = self.session.lines[index.row()]
        value = str(value) if field == "text" else str(value).strip()
        if getattr(line, field) == value:
            return False
        self.session.set_line(index.row(), replace(line, **{field: value}))
        self.dataChanged.emit(index, index)
        return True


class ChoiceDelegate(QStyledItemDelegate):
    """Combo box editor whose choices come from a callable."""

    def __init__(self, choices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.choices = choices

    def createEditor(self, parent: QWidget, option, index: Index) -> QWidget:  # noqa: N802
        combo = QComboBox(parent)
        combo.addItems(list(self.choices()))
        return combo

    def setEditorData(self, editor: QWidget, index: Index) -> None:  # noqa: N802
        assert isinstance(editor, QComboBox)
        value = str(index.data(Qt.ItemDataRole.EditRole) or "")
        if editor.findText(value) < 0:
            editor.addItem(value)
        editor.setCurrentText(value)

    def setModelData(self, editor: QWidget, model, index: Index) -> None:  # noqa: N802
        assert isinstance(editor, QComboBox)
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class LinesTab(QWidget):
    play_requested = Signal(str)
    regenerate_requested = Signal(str)
    status_message = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self._busy = False

        # Banner for read-only sources.
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.convert_button = QPushButton("Convert to JSON")
        self.convert_button.setToolTip(
            "Write lines.json next to the CSV file and use it from now on. The CSV file is kept."
        )
        self.convert_button.clicked.connect(self._convert)
        banner_row = QHBoxLayout()
        banner_row.addWidget(self.banner, 1)
        banner_row.addWidget(self.convert_button)
        self.banner_box = QWidget()
        self.banner_box.setLayout(banner_row)
        banner_row.setContentsMargins(0, 0, 0, 0)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by ID, voice, tone or text")
        self.filter.setClearButtonEnabled(True)
        self.count_label = QLabel()

        self.model = LinesModel(session)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.filter.textChanged.connect(self.proxy.setFilterFixedString)
        self.filter.textChanged.connect(self._update_count)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(self.fontMetrics().height() + 8)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)
        header.setHighlightSections(False)
        self.table.setItemDelegateForColumn(1, ChoiceDelegate(lambda: self.session.voices, self))
        self.table.setItemDelegateForColumn(
            2, ChoiceDelegate(lambda: sorted(self.session.tones), self)
        )
        self.table.setItemDelegateForColumn(3, ChoiceDelegate(lambda: KINDS, self))
        self.table.selectionModel().selectionChanged.connect(self._update_enabled)
        self.table.doubleClicked.connect(self._double_clicked)
        delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self.table)
        delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_shortcut.activated.connect(self.delete_lines)

        self.empty = QLabel("No lines yet. Add a line, or point voicebake.toml at a CSV file.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setEnabled(False)

        self.add_button = QPushButton("Add Line")
        self.add_button.clicked.connect(self.add_line)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_lines)
        self.play_button = QPushButton("Play")
        self.play_button.setToolTip("Play the baked audio for the selected line.")
        self.play_button.clicked.connect(self._play)
        self.regen_button = QPushButton("Regenerate")
        self.regen_button.setToolTip("Bake the selected line again now, saving any edits first.")
        self.regen_button.clicked.connect(self._regenerate)
        self.human_button = QPushButton("Mark as Human Take")
        self.human_button.setToolTip(
            "A recorded take replaces this line: bakes will never overwrite its audio file."
        )
        self.human_button.clicked.connect(self._toggle_human)

        top = QHBoxLayout()
        top.addWidget(QLabel("Filter:"))
        top.addWidget(self.filter, 1)
        top.addSpacing(12)
        top.addWidget(self.count_label)

        bottom = QHBoxLayout()
        bottom.addWidget(self.add_button)
        bottom.addWidget(self.delete_button)
        bottom.addStretch(1)
        bottom.addWidget(self.play_button)
        bottom.addWidget(self.regen_button)
        bottom.addWidget(self.human_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.banner_box)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.empty, 1)
        layout.addLayout(bottom)

        session.lines_changed.connect(self._lines_changed)
        session.states_changed.connect(self._update_enabled)
        session.states_changed.connect(self._fit_columns)
        self._lines_changed()

    # -- state ---------------------------------------------------------------------------

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_enabled()

    def _lines_changed(self) -> None:
        src = self.session.source
        if self.session.project is None:
            self.banner_box.hide()
        elif src == "csv":
            self.banner.setText(
                "Lines are read from a CSV file and cannot be edited here. "
                "Edit the CSV, or convert it to JSON to edit lines in this window."
            )
            self.convert_button.show()
            self.banner_box.show()
        elif src == "scanner":
            self.banner.setText(
                "Lines are produced by the scanner script set in voicebake.toml and cannot be "
                "edited here. Change them in the game files, then reload (F5)."
            )
            self.convert_button.hide()
            self.banner_box.show()
        else:
            self.banner_box.hide()
        has = bool(self.session.lines)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self._fit_columns()
        self._update_count()
        self._update_enabled()

    def _fit_columns(self) -> None:
        if not self.session.lines:
            return
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        for col in range(len(COLUMNS)):
            if col != COL_TEXT:
                header.resizeSection(col, min(header.sectionSize(col) + 12, 200))
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)

    def _update_count(self) -> None:
        total = len(self.session.lines)
        shown = self.proxy.rowCount()
        word = "line" if total == 1 else "lines"
        self.count_label.setText(
            f"{total} {word}" if shown == total else f"{shown} of {total} {word}"
        )

    def selected_rows(self) -> list[int]:
        rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
        return sorted(rows)

    def _current_line(self):
        rows = self.selected_rows()
        return self.session.lines[rows[0]] if len(rows) == 1 else None

    def _update_enabled(self) -> None:
        editable = self.session.lines_editable and self.session.project is not None
        rows = self.selected_rows()
        line = self._current_line()
        state = self.session.states.get(line.id, "") if line else ""
        self.add_button.setEnabled(editable and bool(self.session.voices))
        self.add_button.setToolTip("" if self.session.voices else "Add a voice first.")
        self.delete_button.setEnabled(editable and bool(rows))
        self.play_button.setEnabled(line is not None and self.session.take_path(line).is_file())
        can_regen = (
            line is not None
            and not self._busy
            and not self.session.read_only
            and state not in ("human", "invalid")
        )
        self.regen_button.setEnabled(can_regen)
        self.human_button.setEnabled(line is not None and not self.session.read_only)
        self.human_button.setText("Unmark Human Take" if state == "human" else "Mark as Human Take")

    # -- actions -------------------------------------------------------------------------

    def add_line(self) -> None:
        if not self.session.lines_editable or not self.session.voices:
            return
        rows = self.selected_rows()
        self.filter.clear()
        row = self.session.add_line(rows[-1] if rows else None)
        index = self.proxy.mapFromSource(self.model.index(row, COL_TEXT))
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index)
        self.table.edit(index)

    def delete_lines(self) -> None:
        rows = self.selected_rows()
        if not rows or not self.session.lines_editable:
            return
        what = f"'{self.session.lines[rows[0]].id}'" if len(rows) == 1 else f"{len(rows)} lines"
        answer = QMessageBox.question(
            self,
            "Delete Lines",
            f"Delete {what}?\n\nAudio already baked for them is not deleted.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.session.remove_lines(rows)

    def _double_clicked(self, index: QModelIndex) -> None:
        if index.column() == COL_STATE or not self.session.lines_editable:
            self._play()

    def _play(self) -> None:
        line = self._current_line()
        if line is not None and self.session.take_path(line).is_file():
            self.play_requested.emit(str(self.session.take_path(line)))

    def _regenerate(self) -> None:
        line = self._current_line()
        if line is not None:
            self.regenerate_requested.emit(line.id)

    def _toggle_human(self) -> None:
        line = self._current_line()
        if line is None:
            return
        human = self.session.states.get(line.id) != "human"
        self.session.set_human(line, human)
        self.status_message.emit(
            f"{line.id} marked as a human take." if human else f"{line.id} will be baked again."
        )

    def _convert(self) -> None:
        if self.session.dirty:
            return
        try:
            path = self.session.convert_csv_to_json()
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Convert to JSON", str(e))
            return
        self.status_message.emit(f"Lines converted to {path.name}.")
