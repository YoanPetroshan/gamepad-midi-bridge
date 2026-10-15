"""Small panel for editing one input's mapping. Changes apply immediately."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

from i18n import tr
from mapping import (GYRO_IDS, INPUT_LABELS, STICK_IDS, TOUCH_IDS, TRIGGER_IDS, AxisMapping, ButtonMapping,
                     copy_settings_into, layer_label, settings_from_text, settings_to_text, unreliable_inputs)
from ui.valuebox import PlainSpin, ValueBox

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(n: int) -> str:
    # Convention C3 = 60 (as in most DAWs and Lightkey/Logic)
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 2}"


def _combo(items: list[tuple[str, str]]) -> QComboBox:
    c = QComboBox()
    for value, text in items:
        c.addItem(text, value)
    return c


def _set_combo(c: QComboBox, value: str) -> None:
    i = c.findData(value)
    if i >= 0:
        c.setCurrentIndex(i)


class MappingPopover(QFrame):
    def __init__(self, parent: QWidget, input_id: str, mapping, on_change: Callable[[str], None],
                 extra: dict | None = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("popover")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.input_id = input_id
        self.m = mapping
        self.on_change = on_change
        self.extra = extra or {}
        self._loading = True
        self._editable = True  # False: an axis that only shows the settings it inherits in this layer

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        title = QLabel(INPUT_LABELS[input_id])
        title.setObjectName("h")
        sub = QLabel(input_id)
        sub.setObjectName("muted")
        head.addWidget(title)
        head.addWidget(sub)
        head.addStretch()
        layer = self.extra.get("layer", "")
        if isinstance(mapping, ButtonMapping) or layer:
            chip = QLabel(tr("Layer: {}", "Слой: {}").format(layer_label(layer)))
            chip.setStyleSheet("color: #b48ef0; border: 1px solid #b48ef0; border-radius: 9px; padding: 1px 8px;")
            head.addWidget(chip)
        lay.addLayout(head)
        if self.extra.get("inherited"):
            note = QLabel(tr("A modifier here by inheritance from a lower layer.\n"
                             "Tick “Enabled” and assign something else to override it in this layer.",
                             "Тук е модификатор по наследство от по-нисък слой.\n"
                             "Включи „Активен“ и задай друго, за да го отмениш в този слой."))
            note.setStyleSheet("color: #b48ef0;")
            lay.addWidget(note)
        if input_id in unreliable_inputs() and not self.extra.get("seen"):
            warn = QLabel(tr("Not detected on this Mac. Over Bluetooth macOS may\n"
                             "intercept this button. Don't use it for important functions.",
                             "Не е открит на този Mac. По Bluetooth macOS може да\n"
                             "прихваща този бутон. Не го ползвай за важни функции."))
            warn.setStyleSheet("color: #f0a840;")
            lay.addWidget(warn)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(7)
        lay.addLayout(self.form)

        self.enabled = QCheckBox(tr("Enabled", "Активен"))
        self.form.addRow("", self.enabled)
        if isinstance(mapping, ButtonMapping):
            self._build_button()
        else:
            self._build_axis()
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText(tr("e.g. Pan 1, Strobe, Scene 2…", "напр. Pan 1, Strobe, Сцена 2…"))
        self.form.addRow(tr("Label", "Етикет"), self.label_edit)
        self._load()
        self._connect_common()
        self._build_tools(lay)
        self._loading = False
        self._refresh_visibility()
        self._refresh_tools()
        self.setMinimumWidth(370)

    # ---------------------------------------------------------------- copy / paste
    def _kind(self) -> str:
        return "button" if isinstance(self.m, ButtonMapping) else "axis"

    def _build_tools(self, lay):
        row = QHBoxLayout()
        self.copy_btn = QPushButton(tr("Copy settings", "Копирай настройките"))
        self.copy_btn.setToolTip(tr("Copies everything of this input (note, CC, channel, mode, speed…) so you can "
                                    "paste it on another button, in another layer or profile, or send it to a friend.",
                                    "Копира всичко от този вход (нота, CC, канал, режим, скорост…), за да го "
                                    "поставиш на друг бутон, в друг слой или профил, или да го пратиш на приятел."))
        self.paste_btn = QPushButton(tr("Paste settings", "Постави настройките"))
        self.paste_btn.setToolTip(tr("Replaces all settings of this input with the copied ones.",
                                     "Замества всички настройки на този вход с копираните."))
        row.addWidget(self.copy_btn)
        row.addWidget(self.paste_btn)
        self.paste_new_btn = None
        if self._kind() == "button":
            self.paste_new_btn = QPushButton(tr("Paste with a new number", "Постави с нов номер"))
            self.paste_new_btn.setToolTip(tr("Same settings, but with the next free note / CC / program number, "
                                             "so two buttons don't send the same thing.",
                                             "Същите настройки, но със следващия свободен номер на нота / CC / "
                                             "програма, за да не пращат два бутона едно и също."))
            row.addWidget(self.paste_new_btn)
        lay.addLayout(row)
        self.tool_status = QLabel()
        self.tool_status.setObjectName("muted")
        lay.addWidget(self.tool_status)
        self.copy_btn.clicked.connect(self._copy)
        self.paste_btn.clicked.connect(lambda: self._paste(False))
        if self.paste_new_btn is not None:
            self.paste_new_btn.clicked.connect(lambda: self._paste(True))

    def _clipboard_settings(self):
        return settings_from_text(QGuiApplication.clipboard().text(), self._kind())

    def _refresh_tools(self):
        ok = self._editable and self._clipboard_settings() is not None
        self.paste_btn.setEnabled(ok)
        if self.paste_new_btn is not None:
            self.paste_new_btn.setEnabled(ok)

    def showEvent(self, e):
        self._refresh_tools()  # something may have been copied since this panel was created
        super().showEvent(e)

    def _copy(self):
        QGuiApplication.clipboard().setText(settings_to_text(self.m))
        self.tool_status.setText(tr("Copied. Open another input and press “Paste settings”.",
                                    "Копирано. Отвори друг вход и натисни „Постави настройките“."))
        self._refresh_tools()

    def _next_free_number(self, kind: str, channel: int) -> int | None:
        used = self._usage(kind, channel, (self.extra.get("layer", ""), self.input_id))
        order = list(range(57, 128)) + list(range(0, 57)) if kind == "note" else range(0, 128)
        return next((n for n in order if n not in used), None)

    def _paste(self, new_number: bool):
        src = self._clipboard_settings()
        if src is None or not self._editable:
            return
        if self._kind() == "axis":
            src = src.adapted_for(self.input_id)
        elif new_number and src.action == "midi":
            n = self._next_free_number(src.type, src.channel)
            if n is not None:
                src.number = n
        copy_settings_into(self.m, src)
        self._reload()
        self.on_change(self.input_id)
        self.tool_status.setText(tr("Pasted.", "Поставено."))

    def _reload(self):
        """Show the settings of `self.m` again (after a paste, or when an axis changes layer settings)."""
        self._loading = True
        self._load()
        self._loading = False
        self._refresh_visibility()
        self._refresh_tools()

    # ---------------------------------------------------------------- button
    def _build_button(self):
        self.action = _combo([("midi", "MIDI"),
                              ("modifier", tr("Modifier (hold → new layer)", "Модификатор (задръж → нов слой)")),
                              ("center_left", tr("Center left stick (Pan/Tilt 1)", "Център ляв стик (Pan/Tilt 1)")),
                              ("center_right", tr("Center right stick (Pan/Tilt 2)", "Център десен стик (Pan/Tilt 2)")),
                              ("center", tr("Center all Pan/Tilt", "Център всички Pan/Tilt")),
                              ("fine", tr("Fine (while held)", "Фино (докато е натиснат)")),
                              ("gyro", tr("Gyro (PlayStation): moves with the controller",
                                          "Жиро (PlayStation): мести с контролера"))])
        self.glide = PlainSpin()
        self.glide.setRange(0.0, 10.0)
        self.glide.setSingleStep(0.1)
        self.glide.setDecimals(1)
        self.glide.setSuffix(tr(" s", " сек"))
        self.glide.setToolTip(tr("How smoothly Pan/Tilt glide back to the middle. 0 = instant.\n"
                                 "Shared by all “Center” buttons in the profile.",
                                 "Колко плавно се връщат Pan/Tilt към средата. 0 = веднага.\n"
                                 "Настройката е обща за всички бутони „Център“ в профила."))
        opts = self.extra.get("options")
        self.glide.setValue(opts.center_time if opts else 1.0)
        self.glide.valueChanged.connect(self._glide_changed)
        self.type = _combo([("note", "Note"), ("cc", "CC"), ("pc", "Program Change")])
        self.mode = QComboBox()
        self.channel = ValueBox(1, 16)
        self.number = ValueBox(0, 127, describe=self._describe_number, owners=self._number_owners)
        self.note_lbl = QLabel()
        self.note_lbl.setObjectName("muted")
        num_row = QWidget()
        nl = QHBoxLayout(num_row)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.addWidget(self.number, 1)
        nl.addWidget(self.note_lbl)
        self.value = ValueBox(0, 127)
        self.form.addRow(tr("Function", "Функция"), self.action)
        self.form.addRow(tr("Glide time", "Връщане за"), self.glide)
        self.form.addRow(tr("Type", "Тип"), self.type)
        self.form.addRow(tr("Mode", "Режим"), self.mode)
        self.form.addRow(tr("Channel", "Канал"), self.channel)
        self.form.addRow(tr("Number", "Номер"), num_row)
        self.form.addRow("Velocity", self.value)
        self.num_row = num_row
        for w in (self.action, self.type, self.mode):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.channel, self.number, self.value):
            w.valueChanged.connect(self._changed)

    def _fill_modes(self):
        t = self.type.currentData()
        cur = self.mode.currentData() or self.m.mode
        self.mode.blockSignals(True)
        self.mode.clear()
        if getattr(self, "action", None) is not None and self.action.currentData() in ("modifier", "gyro"):
            # for a modifier / the gyro: hold it, or switch it on and off with each press
            self.mode.addItem(tr("Hold (active while pressed)", "Задържане (активен, докато е натиснат)"), "momentary")
            self.mode.addItem(tr("Toggle (press on, press again off)", "Toggle (натисни – вкл., пак – изкл.)"), "toggle")
        else:
            self.mode.addItem(tr("Momentary (press/release)", "Momentary (натиснат/пуснат)"), "momentary")
            self.mode.addItem(tr("Toggle (on/off)", "Toggle (вкл./изкл.)"), "toggle")
        if t == "cc":
            self.mode.addItem(tr("Fixed value", "Фиксирана стойност"), "value")
        _set_combo(self.mode, cur)
        if self.mode.currentIndex() < 0:
            self.mode.setCurrentIndex(0)
        self.mode.blockSignals(False)

    # ---------------------------------------------------------------- what is already taken
    def _usage(self, kind: str, channel: int, exclude) -> dict[int, list[str]]:
        provider = self.extra.get("usage")
        return provider(kind, channel, exclude) if provider else {}

    def _number_owners(self) -> dict[int, list[str]]:
        return self._usage(self.m.type, self.m.channel, (self.extra.get("layer", ""), self.input_id))

    def _cc_owners(self) -> dict[int, list[str]]:
        return self._usage("cc", self.m.channel, ("", self.input_id))

    def _describe_number(self, n: int) -> str:
        return note_name(n) if self.m.type == "note" else ""

    def _glide_changed(self, v):
        opts = self.extra.get("options")
        if opts is not None and not self._loading:
            opts.center_time = float(v)
            self.extra.get("options_changed", lambda: None)()

    # ---------------------------------------------------------------- axis
    def _build_axis(self):
        if self.input_id in TOUCH_IDS:
            modes = [("relative", tr("Drag (like a trackpad)", "Плъзгане (като тракпад)")),
                     ("absolute", tr("Absolute (XY pad)", "Абсолютен (XY пад)"))]
        else:
            modes = [("rate", tr("Rate (speed)", "Скоростен (скорост)")),
                     ("absolute", tr("Absolute (position)", "Абсолютен (позиция)"))]
        self.amode = _combo(modes)
        self.channel = ValueBox(1, 16)
        self.cc = ValueBox(0, 127, owners=self._cc_owners)
        self.hires = QCheckBox(tr("14-bit (MSB on CC n, LSB on CC n+32)", "14-бит (MSB на CC n, LSB на CC n+32)"))
        self.deadzone = PlainSpin()
        self.deadzone.setRange(0.0, 0.9)
        self.deadzone.setSingleStep(0.01)
        self.deadzone.setDecimals(2)
        self.curve = _combo([("linear", tr("Linear", "Линейна")), ("expo", tr("Exponential", "Експоненциална"))])
        self.expo = PlainSpin()
        self.expo.setRange(0.0, 1.0)
        self.expo.setSingleStep(0.05)
        self.expo.setDecimals(2)
        self.expo.setToolTip(tr("0 = linear, 1 = softest around the center", "0 = линейна, 1 = максимално мека около центъра"))
        curve_row = QWidget()
        cl = QHBoxLayout(curve_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.curve, 1)
        cl.addWidget(QLabel(tr("amount", "сила")))
        cl.addWidget(self.expo)
        self.curve_row = curve_row
        self.speed = PlainSpin()
        self.speed.setRange(0.05, 5.0)
        self.speed.setSingleStep(0.05)
        self.speed.setDecimals(2)
        self.span = PlainSpin()
        self.span.setRange(0.05, 1.0)
        self.span.setSingleStep(0.05)
        self.span.setDecimals(2)
        self.span.setPrefix("× ")
        self.span.setToolTip(tr("Which part of the full range full deflection covers, around the middle.\n"
                                "1.00 = the whole range; 0.50 = only the middle half, for precise work.",
                                "Каква част от целия обхват покрива пълното отклонение, около средата.\n"
                                "1.00 = целият обхват; 0.50 = само средната половина, за прецизна работа."))
        self.hold = QCheckBox(tr("Hold position when released", "Задръж позицията при пускане"))
        self.hold.setToolTip(tr(
            "The stick's spring back to center is ignored: the head stays where you left it.\n"
            "The stick takes over again when it reaches that position (no jump).",
            "Връщането на стика от пружината се игнорира: главата остава, където си я оставил.\n"
            "Стикът я поема отново, когато стигне до тази позиция (без скок)."))
        self.invert = QCheckBox(tr("Invert direction", "Инвертирай посоката"))
        layer = self.extra.get("layer", "")
        if layer:  # inside a layer: the axis may have its own settings there
            self.own = QCheckBox(tr("Own settings in this layer", "Собствени настройки в този слой"))
            self.own.setToolTip(tr("Off: the axis behaves as in the base layer (or the layer it inherits from).\n"
                                   "On: it starts as a copy and you can change anything here: speed, absolute "
                                   "position, even another CC. Nothing jumps when you switch layers.",
                                   "Изключено: оста се държи както в основния слой (или в слоя, от който наследява).\n"
                                   "Включено: започва като копие и можеш да промениш всичко тук: скорост, абсолютна "
                                   "позиция, дори друг CC. При смяна на слоя няма скокове."))
            self.own_note = QLabel()
            self.own_note.setObjectName("muted")
            self.own_note.setWordWrap(True)
            self.form.addRow("", self.own)
            self.form.addRow("", self.own_note)
            src = self.extra.get("axis_source", lambda: None)()
            self.own.setChecked(src == layer)
            self._editable = src == layer
            self._update_own_note()
            self.own.toggled.connect(self._own_toggled)
        self.form.addRow(tr("Mode", "Режим"), self.amode)
        self.form.addRow(tr("Channel", "Канал"), self.channel)
        self.form.addRow("CC", self.cc)
        self.form.addRow("", self.hires)
        self.form.addRow("Deadzone", self.deadzone)
        self.form.addRow(tr("Curve", "Крива"), curve_row)
        self.form.addRow(tr("Sensitivity", "Чувствителност"), self.speed)
        self.form.addRow(tr("Sensitivity", "Чувствителност"), self.span)
        self.form.addRow("", self.hold)
        self.form.addRow("", self.invert)
        self.center_btn = QPushButton(tr("Center (64)", "Център (64)"))
        self.center_btn.clicked.connect(lambda: self.extra.get("center_axis", lambda _: None)(self.input_id))
        self.form.addRow("", self.center_btn)
        for w in (self.amode, self.curve):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.channel, self.cc, self.deadzone, self.expo, self.speed, self.span):
            w.valueChanged.connect(self._changed)
        self.hires.toggled.connect(self._changed)
        self.hold.toggled.connect(self._changed)
        self.invert.toggled.connect(self._changed)

    def _update_own_note(self):
        layer = self.extra.get("layer", "")
        src = self.extra.get("axis_source", lambda: None)()
        if src == layer:
            text = tr("This layer has its own settings for this axis.", "Този слой има собствени настройки за тази ос.")
        elif src is None:
            text = tr("Using the base settings of this axis.", "Ползва основните настройки на оста.")
        else:
            text = tr("Using the settings of the layer “{}”.", "Ползва настройките на слой „{}“.").format(layer_label(src))
        self.own_note.setText(text)

    def _own_toggled(self, on: bool):
        if self._loading:
            return
        make = self.extra.get("override_create" if on else "override_remove")
        if make is None:
            return
        self.m = make()
        self._editable = on
        self._update_own_note()
        self._reload()
        self.on_change(self.input_id)

    # ---------------------------------------------------------------- data
    def _load(self):
        m = self.m
        self.enabled.setChecked(m.enabled)
        self.label_edit.setText(m.label)
        if isinstance(m, ButtonMapping):
            _set_combo(self.action, m.action)
            _set_combo(self.type, m.type)
            self._fill_modes()
            _set_combo(self.mode, m.mode)
            self.channel.setValue(m.channel)
            self.number.setValue(m.number)
            self.value.setValue(m.value)
        else:
            _set_combo(self.amode, m.mode)
            self.channel.setValue(m.channel)
            self.cc.setValue(m.cc)
            self.hires.setChecked(m.hires)
            self.deadzone.setValue(m.deadzone)
            _set_combo(self.curve, m.curve)
            self.expo.setValue(m.expo)
            self.speed.setValue(m.max_speed)
            self.span.setValue(m.span)
            self.hold.setChecked(m.hold)
            self.invert.setChecked(m.invert)

    def _connect_common(self):
        self.enabled.toggled.connect(self._changed)
        self.label_edit.textChanged.connect(self._changed)

    def _changed(self, *_):
        if self._loading or not self._editable:
            return
        m = self.m
        m.enabled = self.enabled.isChecked()
        m.label = self.label_edit.text().strip()
        if isinstance(m, ButtonMapping):
            if self.sender() in (self.type, self.action):
                self._fill_modes()
            m.action = self.action.currentData()
            m.type = self.type.currentData()
            m.mode = self.mode.currentData() or "momentary"
            m.channel = self.channel.value()
            m.number = self.number.value()
            m.value = self.value.value()
            n = m.normalized()
            m.mode = n.mode
        else:
            m.mode = self.amode.currentData()
            m.channel = self.channel.value()
            m.cc = self.cc.value()
            m.hires = self.hires.isChecked() and m.cc < 32
            m.deadzone = self.deadzone.value()
            m.curve = self.curve.currentData()
            m.expo = self.expo.value()
            m.max_speed = self.speed.value()
            m.span = self.span.value()
            m.hold = self.hold.isChecked()
            m.invert = self.invert.isChecked()
        self._refresh_visibility()
        self.on_change(self.input_id)

    def _show_row(self, field: QWidget, visible: bool):
        self.form.setRowVisible(field, visible)

    def _refresh_visibility(self):
        m = self.m
        if isinstance(m, ButtonMapping):
            midi = m.action == "midi"
            if m.action == "modifier" and not self._loading:
                self.extra.get("layers_changed", lambda: None)()
            self._show_row(self.glide, m.action.startswith("center"))
            for w in (self.type, self.mode, self.channel, self.num_row, self.value):
                self._show_row(w, midi)
            if m.action in ("gyro", "modifier"):
                self._show_row(self.mode, True)  # hold = while pressed, toggle = on/off
            if midi:
                self._show_row(self.mode, m.type != "pc")
                show_val = m.type == "note" or (m.type == "cc" and m.mode == "value")
                self._show_row(self.value, show_val)
                lbl = self.form.labelForField(self.value)
                if lbl:
                    lbl.setText("Velocity" if m.type == "note" else tr("Value", "Стойност"))
                nl = self.form.labelForField(self.num_row)
                if nl:
                    nl.setText({"note": tr("Note", "Нота"), "cc": "CC №", "pc": tr("Program", "Програма")}[m.type])
                self.note_lbl.setText(note_name(m.number) if m.type == "note" else "")
        else:
            a = self.input_id
            gyro, touch, stick = a in GYRO_IDS, a in TOUCH_IDS, a in STICK_IDS
            moving = gyro or m.mode in ("rate", "relative")  # sensitivity = speed / drag amount
            self._show_row(self.amode, not gyro)  # the gyro is always a speed
            self._show_row(self.speed, moving)
            self._show_row(self.span, not moving)
            self._show_row(self.hold, stick and m.mode == "absolute")
            self._show_row(self.deadzone, not touch)
            self._show_row(self.curve_row, not touch)
            self.speed.setSuffix(tr(" range/swipe", " обхв./плъзгане") if m.mode == "relative" and touch
                                 else tr(" range/s", " обхв./сек"))
            self.speed.setToolTip(
                tr("How far one full swipe across the touchpad moves the value (0.50 = half the range).",
                   "Колко мести стойността едно цяло плъзгане по тъчпада (0.50 = половин обхват).")
                if touch else
                tr("At full deflection: what fraction of the full range is covered per second.\n"
                   "0.50 = end to end in 2 seconds.",
                   "При пълно изместване: каква част от целия обхват се изминава за секунда.\n"
                   "0.50 = от край до край за 2 секунди."))
            self._show_row(self.center_btn, moving or touch or (stick and m.hold))
            for w in (self.enabled, self.amode, self.channel, self.cc, self.deadzone, self.curve, self.speed,
                      self.span, self.hold, self.invert, self.center_btn, self.label_edit):
                w.setEnabled(self._editable)
            self.expo.setEnabled(self._editable and m.curve == "expo")
            self.hires.setEnabled(self._editable and m.cc < 32)
            self.hires.setToolTip("" if m.cc < 32 else tr("14-bit is only possible for CC 0–31 (LSB = CC+32).",
                                                                   "14-бит е възможен само за CC 0–31 (LSB = CC+32)."))
            if self.input_id in TRIGGER_IDS:
                self.center_btn.setText(tr("Reset value (64)", "Нулирай стойността (64)"))
        self.adjustSize()

    # ---------------------------------------------------------------- position
    def show_near(self, anchor: QRectF, prefer_left: bool):
        self.adjustSize()
        screen = QGuiApplication.screenAt(anchor.center().toPoint()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = self.width(), self.height()
        if prefer_left:
            x = anchor.right() + 10
        else:
            x = anchor.left() - w - 10
        y = anchor.top() - 10
        x = max(avail.left() + 8, min(x, avail.right() - w - 8))
        y = max(avail.top() + 8, min(y, avail.bottom() - h - 8))
        self.move(int(x), int(y))
        self.show()
