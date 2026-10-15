"""An integer field you can type in, with a drop-down list of every allowed value.

Replaces QSpinBox's tiny up/down arrows in the mapping editor:
  * click the text and type a new number (the whole number is selected on focus), or
  * open the list and pick a value. Values already used elsewhere are marked with
    the button and layer that use them.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIntValidator, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QDoubleSpinBox, QLineEdit

from ui import theme


class _NumberEdit(QLineEdit):
    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)  # click, then simply type the new number


class ValueBox(QComboBox):
    valueChanged = Signal(int)  # emitted when the user changes the value (not by setValue)

    def __init__(self, lo: int, hi: int, parent=None,
                 describe: Callable[[int], str] | None = None,
                 owners: Callable[[], dict[int, list[str]]] | None = None):
        super().__init__(parent)
        self.lo, self.hi = lo, hi
        self._value = lo
        self._describe = describe  # value → short text, e.g. a note name
        self._owners = owners  # () → {value: ["A · Base", ...]}, read each time the list opens
        self.setEditable(True)
        self.setLineEdit(_NumberEdit())
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setCompleter(None)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMaxVisibleItems(14)
        self.setMinimumContentsLength(3)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        le = self.lineEdit()
        # the box around the combo is enough: no second frame or extra padding for the text inside
        le.setStyleSheet("QLineEdit { border: none; background: transparent; padding: 0px 2px; }")
        le.setValidator(QIntValidator(lo, hi, self))
        le.textEdited.connect(self._typed)
        le.editingFinished.connect(self._finished)
        self.activated.connect(self._picked)
        self.setModel(QStandardItemModel(self))
        self._rebuild()
        self.setValue(lo)

    # ---------------------------------------------------------------- value
    def value(self) -> int:
        return self._value

    def setValue(self, v: int) -> None:
        """Set the value without emitting valueChanged."""
        self._value = max(self.lo, min(self.hi, int(v)))
        self.blockSignals(True)
        self.setCurrentIndex(self._value - self.lo)
        self.lineEdit().setText(str(self._value))
        self.blockSignals(False)

    def _set_from_user(self, v: int) -> None:
        v = max(self.lo, min(self.hi, v))
        if v != self._value:
            self._value = v
            self.valueChanged.emit(v)

    def _typed(self, text: str) -> None:
        if text.strip().lstrip("-").isdigit():
            v = int(text)
            if self.lo <= v <= self.hi:
                self._set_from_user(v)  # applied as you type, as long as it is a valid number

    def _finished(self) -> None:
        text = self.lineEdit().text().strip()
        if text.isdigit():
            self._set_from_user(int(text))
        self.lineEdit().setText(str(self._value))  # an empty or out-of-range entry falls back

    def _picked(self, index: int) -> None:
        v = self.itemData(index)
        if v is not None:
            self.lineEdit().setText(str(v))  # the field shows just the number, not the long list text
            self._set_from_user(int(v))

    # ---------------------------------------------------------------- list
    def set_providers(self, describe=None, owners=None) -> None:
        self._describe, self._owners = describe, owners

    def _row_text(self, v: int, owners: dict[int, list[str]]) -> tuple[str, bool]:
        text = str(v)
        if self._describe:
            d = self._describe(v)
            if d:
                text += f"   {d}"
        who = owners.get(v)
        if who:
            text += "   ←   " + who[0] + (f"  +{len(who) - 1}" if len(who) > 1 else "")
        return text, bool(who)

    def _rebuild(self) -> None:
        owners = self._owners() if self._owners else {}
        model: QStandardItemModel = self.model()
        model.clear()
        widest = 0
        fm = self.fontMetrics()
        for v in range(self.lo, self.hi + 1):
            text, used = self._row_text(v, owners)
            item = QStandardItem(text)
            item.setData(v, Qt.UserRole)
            if used:
                item.setForeground(QColor(theme.WARN))
            model.appendRow(item)
            widest = max(widest, fm.horizontalAdvance(text))
        self.view().setMinimumWidth(min(560, widest + 48))

    def showPopup(self) -> None:
        self.blockSignals(True)
        self._rebuild()  # the owners may have changed since the last time
        self.setCurrentIndex(self._value - self.lo)
        self.lineEdit().setText(str(self._value))  # selecting a row would copy its long text into the field
        self.blockSignals(False)
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self.lineEdit().setText(str(self._value))

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()  # scrolling over the panel must not change values by accident


class PlainSpin(QDoubleSpinBox):
    """A decimal field without the up/down arrows: click it and type the number."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.setFocusPolicy(Qt.StrongFocus)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.lineEdit().selectAll)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()
