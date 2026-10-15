"""Main window."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSplitter,
                               QStatusBar, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from engine import Engine
from input_reader import ReaderProcess
import mapping
import updater
from mapping import (AXIS_IDS, BUTTON_IDS, DEFAULT_PROFILE_NAME, GYRO_IDS, INPUT_LABELS, PADDLE_IDS,
                     TOUCH_IDS, UNRELIABLE_INPUTS, unreliable_inputs,
                     ProfileStore, default_profile, layer_label, layer_mods)
import feedback
import i18n
from i18n import tr
from midi_out import MidiOut
from ui import theme
from ui.controller_view import ControllerView
from ui.panels import MonitorPanel, SettingsPanel, TestPanel
from ui.popover import MappingPopover
from ui.about_dialog import AboutDialog, FeedbackDialog
from ui.update_dialog import UpdateController, show_whats_new
from version import APP_VERSION

UI_HZ = 30


def _parse_slot(text: str):
    """"1:10:0" → (1, 10, False): the key a held value is saved under (channel : CC : 14-bit)."""
    try:
        ch, cc, hi = text.split(":")
        return int(ch), int(cc), hi == "1"
    except ValueError:
        return None


def _slot_text(slot) -> str:
    return f"{slot[0]}:{slot[1]}:{int(slot[2])}"


def displayed_layer(edit_layer: str, pinned: bool, live: str, prev_live: str) -> str:
    """Which layer the diagram shows after the held modifiers changed from `prev_live` to `live`.

    Holding a modifier shows its layer. Letting go returns to the base layer, unless the layer
    is pinned ("Keep layer"), so you can edit it without holding the button.
    """
    if live == prev_live:
        return edit_layer
    if live:
        return live
    return edit_layer if pinned else ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Xbox MIDI Bridge {APP_VERSION}")
        self.resize(1500, 860)

        self.store = ProfileStore()
        st = self.store.settings
        self.profile = self.store.load_active()
        self.midi = MidiOut()
        self.midi.open(st.get("midi_port"))
        self.reader = ReaderProcess()
        self.reader.start(st.get("controller"))
        keep = bool(st.get("persist_rate_values"))
        slots = {_parse_slot(k): v for k, v in (st.get("rate_slots") or {}).items() if _parse_slot(k)} if keep else None
        legacy = st.get("rate_values") if keep and not st.get("rate_slots") else None  # saved per axis by 1.6 and older
        self.engine = Engine(self.profile, self.midi, self.reader, rate_values=legacy, slot_values=slots)
        self.engine.reader_prefer = st.get("controller")
        self.engine.seen.update(i for i in st.get("seen_inputs", []) if i in UNRELIABLE_INPUTS)
        self.engine.start()
        self._popover: MappingPopover | None = None
        self._last_rate_save = time.time()
        self._devices_shown: list[str] | None = None
        self.edit_layer = ""  # the layer being shown and edited
        self._live_layer = ""  # the layer of the modifiers held on the controller right now
        self._known_layers: set[str] = set()  # layers that existed at the last refresh

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(300)
        self._save_timer.timeout.connect(lambda: self.store.save_profile(self.profile))

        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / UI_HZ))
        self.timer.timeout.connect(self.tick)

        self.updates = UpdateController(self, self.store.settings, self.store.save_settings, self.close)
        self._build_ui()
        self.timer.start()
        self._whats_new_after_update()
        if st.get("auto_update_check", True):
            QTimer.singleShot(3000, self.updates.check)

        if st.get("persist_rate_values") and st.get("resend_on_start"):
            # Give Lightkey time to see the virtual port.
            QTimer.singleShot(1500, self.engine.resend_rate_values)

    # ---------------------------------------------------------------- UI
    def _build_ui(self):
        """Everything you see. It is rebuilt when the language changes; the engine, the MIDI port
        and the controller reader are not touched, so nothing is interrupted."""
        self._build_toolbar()
        self._info_applied: dict | None = None
        self.view = ControllerView()
        self.view.set_profile(self.profile)
        self.view.seen_ever = set(self.engine.seen)
        self.view.inputClicked.connect(self.open_editor)

        self.tabs = QTabWidget()
        self.monitor = MonitorPanel(self.midi)
        self.test = TestPanel(self.engine, lambda: self.profile)
        self.settings_panel = SettingsPanel()
        self.tabs.addTab(self.monitor, tr("MIDI monitor", "MIDI монитор"))
        self.tabs.addTab(self.test, tr("Lightkey test", "Тест за Lightkey"))
        self.tabs.addTab(self.settings_panel, tr("Settings", "Настройки"))
        self.tabs.setMinimumWidth(340)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)
        lv.addWidget(self._build_layer_bar())
        lv.addWidget(self.view, 1)
        self._split = QSplitter()
        self._split.addWidget(left)
        self._split.addWidget(self.tabs)
        self._split.setStretchFactor(0, 1)
        self._split.setStretchFactor(1, 0)
        self._split.setSizes([1120, 380])
        self._split.setContentsMargins(8, 8, 8, 8)
        self.setCentralWidget(self._split)  # the previous one, if any, is deleted

        self._build_statusbar()
        self._init_settings_panel()
        self.settings_panel.checkUpdatesRequested.connect(lambda: self.updates.check(manual=True))
        self.settings_panel.whatsNewRequested.connect(lambda: show_whats_new(self, None))
        self._apply_family()
        self._reload_profiles()
        self._refresh_layers()

    def _rebuild_ui(self):
        """Rebuild all windows' texts in the current language, keeping what you were looking at."""
        sizes, tab = self._split.sizes(), self.tabs.currentIndex()
        learn, pinned = self.learn_btn.isChecked(), self.pin_cb.isChecked()
        paused = self.monitor.pause.isChecked()
        if self._popover is not None:
            try:
                self._popover.close()
            except RuntimeError:
                pass
        if getattr(self, "_about", None) is not None:
            self._about.close()
            self._about.deleteLater()
            self._about = None
        old_toolbar = self._toolbar
        self.removeToolBar(old_toolbar)
        old_toolbar.deleteLater()
        self._devices_shown = None
        self._build_ui()
        self._split.setSizes(sizes)
        self.tabs.setCurrentIndex(tab)
        self.learn_btn.blockSignals(True)
        self.learn_btn.setChecked(learn)
        self.learn_btn.blockSignals(False)
        self.view.learn = learn
        self._set_pin(pinned)  # the new checkbox starts unticked; the layer on screen is unchanged
        self.monitor.pause.setChecked(paused)

    def _build_toolbar(self):
        tb = QToolBar(tr("Profiles", "Профили"))
        self._toolbar = tb
        tb.setMovable(False)
        self.addToolBar(tb)
        lbl = QLabel(tr("  Profile ", "  Профил "))
        lbl.setStyleSheet("background: transparent;")
        tb.addWidget(lbl)
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.activated.connect(lambda _: self.switch_profile(self.profile_combo.currentText()))
        tb.addWidget(self.profile_combo)
        for text, slot in ((tr("New", "Нов"), self.new_profile),
                           (tr("Duplicate", "Дублирай"), self.duplicate_profile),
                           (tr("Rename", "Преименувай"), self.rename_profile),
                           (tr("Delete", "Изтрий"), self.delete_profile),
                           (tr("Reset to default", "Върни по подразбиране"), self.reset_profile)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            tb.addWidget(b)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent;")
        tb.addWidget(spacer)
        other = "bg" if i18n.LANG == "en" else "en"
        self.lang_btn = QPushButton("🌐 " + ("BG" if other == "bg" else "EN"))
        self.lang_btn.setToolTip(tr("Switch the interface to Bulgarian (the app restarts)",
                                    "Смени интерфейса на английски (приложението се рестартира)"))
        self.lang_btn.clicked.connect(lambda: self.switch_language(other))
        tb.addWidget(self.lang_btn)
        self.center_btn = QPushButton(tr("Center Pan/Tilt", "Център Pan/Tilt"))
        self.center_btn.setToolTip(tr("Smoothly glides all rate-mode axes back to 64 (or 8192).\n"
                                      "The time is set in Settings → Glide to center.",
                                      "Плавно връща всички оси в скоростен режим към 64 (или 8192).\n"
                                      "Времето се задава в Настройки → Към центъра."))
        self.center_btn.clicked.connect(self.engine.center_all)
        tb.addWidget(self.center_btn)
        self.learn_btn = QPushButton(tr("Learn", "Научи"))
        self.learn_btn.setCheckable(True)
        self.learn_btn.setToolTip(tr("Click, then press a controller button to edit it",
                                     "Натисни, после натисни бутон на контролера, за да го редактираш"))
        self.learn_btn.toggled.connect(self._learn_toggled)
        tb.addWidget(self.learn_btn)
        if not hasattr(self, "_quit_act"):  # a shortcut only: created once, not with every rebuild
            self._quit_act = QAction(tr("Quit", "Изход"), self)
            self._quit_act.setShortcut("Ctrl+Q")
            self._quit_act.triggered.connect(self.close)
            self.addAction(self._quit_act)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)  # replaces (and deletes) the previous one
        self.st_ctrl = QLabel()
        self.st_midi = QLabel()
        self.st_bg = QLabel()
        self.st_fine = QLabel()
        for w in (self.st_ctrl, self.st_midi, self.st_bg):
            sb.addWidget(w)
        sb.addPermanentWidget(self.st_fine)
        # The version: click it for About (updates, what's new, feedback).
        self.st_about = QPushButton(f"ⓘ  Xbox MIDI Bridge {APP_VERSION}")
        self.st_about.setFlat(True)
        self.st_about.setCursor(Qt.PointingHandCursor)
        self.st_about.setToolTip(tr("About · check for updates · send feedback",
                                    "За приложението · провери за обновления · изпрати отзив"))
        self.st_about.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {theme.MUTED};"
                                    f" padding: 0 10px; }} QPushButton:hover {{ color: {theme.ACCENT}; }}")
        self.st_about.clicked.connect(self.show_about)
        sb.addPermanentWidget(self.st_about)

    # ---------------------------------------------------------------- about / feedback
    def feedback_info(self) -> str:
        with self.engine.lock:
            name = self.engine.controller_name if self.engine.connected else None
        return feedback.system_info(name, self.store.settings.get("family"), i18n.LANG)

    def show_about(self):
        if getattr(self, "_about", None) is None:
            self._about = AboutDialog(self, lambda: self.updates.check(manual=True),
                                      lambda: show_whats_new(self, None), self.show_feedback, self.feedback_info)
        self._about.show()  # not modal: the update windows it can open must stay usable
        self._about.raise_()
        self._about.activateWindow()

    def show_feedback(self):
        FeedbackDialog(self, self.feedback_info).exec()

    def _init_settings_panel(self):
        sp = self.settings_panel
        st = self.store.settings
        sp.refresh_ports(st.get("midi_port"))
        sp.set_devices([], st.get("controller"))
        sp.fine.setValue(self.profile.options.fine_factor)
        sp.rate.setValue(self.profile.options.max_rate_hz)
        sp.glide.setValue(self.profile.options.center_time)
        sp.persist.setChecked(bool(st.get("persist_rate_values")))
        sp.resend.setChecked(bool(st.get("resend_on_start")))
        sp.changed.connect(self._settings_changed)
        sp.midiPortChosen.connect(self._choose_port)
        sp.controllerChosen.connect(self._choose_controller)
        sp.resendRequested.connect(self.engine.resend_rate_values)
        sp.language.setCurrentIndex(max(0, sp.language.findData(st.get("language", "auto"))))
        sp.languageChosen.connect(self._choose_language)
        sp.led.blockSignals(True)
        sp.led.setChecked(self.profile.options.led_layers)
        sp.led.blockSignals(False)
        sp.auto_fill.blockSignals(True)
        sp.auto_fill.setChecked(self.profile.options.auto_fill_layers)
        sp.auto_fill.blockSignals(False)
        sp.auto_update.blockSignals(True)
        sp.auto_update.setChecked(bool(st.get("auto_update_check", True)))
        sp.auto_update.blockSignals(False)
        sp.view_family.setCurrentIndex(max(0, sp.view_family.findData(st.get("view_family", "auto"))))
        sp.viewChosen.connect(self._choose_view)

    def _whats_new_after_update(self):
        """First start of a newer version: show what changed since the last version seen."""
        import updater
        st = self.store.settings
        last = st.get("last_seen_version")
        if last is None and self.store.fresh_install:
            last = APP_VERSION  # brand-new install: nothing to tell
        elif last is None:
            last = "1.2.0"  # used the app before this was tracked (1.2.0 or older)
        if updater.is_newer(APP_VERSION, last):
            QTimer.singleShot(700, lambda: show_whats_new(self, last))
        if st.get("last_seen_version") != APP_VERSION:
            st["last_seen_version"] = APP_VERSION
            self.store.save_settings()

    # ---------------------------------------------------------------- controller family
    def _choose_view(self, code: str):
        self.store.settings["view_family"] = code
        self.store.save_settings()
        self._apply_family()

    def _apply_family(self):
        """Labels, diagram and test sliders for Xbox or PlayStation."""
        st = self.store.settings
        detected = st.get("family", "xbox")
        fam = st.get("view_family", "auto")
        fam = detected if fam not in mapping.FAMILIES else fam
        mapping.set_family(fam)
        extras = set(st.get("extras", [])) if fam == detected and st.get("extras") is not None else None
        self.view.set_family(fam, extras)
        visible = self.view.visible_inputs()
        self.test.set_visible([a for a in AXIS_IDS if a in visible])
        self._refresh_layers()

    def _controller_info(self, info: dict):
        """A controller connected: remember its family and optional inputs."""
        extras = [b for b in info.get("has", []) if b == "touchpad" or b in PADDLE_IDS]
        if info.get("touchpad"):
            extras += list(TOUCH_IDS) + ["touchpad"]
        if info.get("gyro"):
            extras += list(GYRO_IDS)
        st = self.store.settings
        st["family"] = info.get("family", "xbox")
        st["extras"] = sorted(set(extras))
        self.store.save_settings()
        self._apply_family()

    def switch_language(self, code: str):
        """Switch the interface language on the fly, without restarting: only the windows are
        rebuilt. The engine, the MIDI port and the controller keep running, nothing is interrupted."""
        self.store.settings["language"] = code
        self.store.save_settings()
        # Deferred: this is called from a widget (the toolbar button, or the Settings list) that the
        # rebuild is about to delete.
        QTimer.singleShot(0, lambda: self._apply_language(code))

    def _apply_language(self, code: str):
        i18n.set_language(code)
        mapping.refresh_labels()
        self._rebuild_ui()

    def _choose_language(self, code: str):
        self.switch_language(code)

    def _settings_changed(self):
        sp = self.settings_panel
        with self.engine.lock:
            self.profile.options.fine_factor = sp.fine.value()
            self.profile.options.max_rate_hz = sp.rate.value()
            self.profile.options.center_time = sp.glide.value()
            self.profile.options.led_layers = sp.led.isChecked()
            self.profile.options.auto_fill_layers = sp.auto_fill.isChecked()
            self.engine._led_layer = None  # repaint the light bar
        self.store.settings["persist_rate_values"] = sp.persist.isChecked()
        self.store.settings["resend_on_start"] = sp.resend.isChecked()
        self.store.settings["auto_update_check"] = sp.auto_update.isChecked()
        sp.resend.setEnabled(sp.persist.isChecked())
        self.store.save_settings()
        self._save_timer.start()

    def _choose_port(self, name):
        with self.engine.lock:
            ok = self.midi.open(name)
        if not ok:
            QMessageBox.warning(self, "MIDI", tr("Could not open the port:\n{}", "Портът не се отвори:\n{}").format(self.midi.error))
            with self.engine.lock:
                self.midi.open(None)
            name = None
            self.settings_panel.refresh_ports(None)
        self.store.settings["midi_port"] = name
        self.store.save_settings()

    def _choose_controller(self, name):
        self.store.settings["controller"] = name
        self.store.save_settings()
        self.engine.reader_prefer = name
        self.reader.prefer(name)

    # ---------------------------------------------------------------- layers
    def _build_layer_bar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(4, 0, 4, 0)
        lbl = QLabel(tr("Layer", "Слой"))
        lbl.setStyleSheet(f"color: {theme.MOD}; font-weight: 600;")
        h.addWidget(lbl)
        self.layer_combo = QComboBox()
        self.layer_combo.setMinimumWidth(240)
        self.layer_combo.setToolTip(tr("Which layer is shown and edited. Hold a modifier on the "
                                       "controller and the app switches to its layer.",
                                       "Кой слой се показва и редактира. Задръж модификатор на "
                                       "контролера и приложението превключва на неговия слой."))
        self.layer_combo.activated.connect(lambda _: self._select_layer(self.layer_combo.currentData()))
        h.addWidget(self.layer_combo)
        self.pin_cb = QCheckBox(tr("Keep layer", "Задръж слоя"))
        self.pin_cb.setToolTip(tr("Off: the diagram shows a layer only while you hold its modifier on the controller, "
                                  "and goes back to the base layer when you let go.\n"
                                  "On: the layer stays on screen so you can edit it without holding the button.",
                                  "Изключено: схемата показва слоя само докато държиш модификатора на контролера и "
                                  "се връща на основния, когато го пуснеш.\n"
                                  "Включено: слоят остава на екрана, за да го редактираш, без да държиш бутона."))
        self.pin_cb.toggled.connect(self._pin_toggled)
        h.addWidget(self.pin_cb)
        self.fill_btn = QPushButton(tr("Fill empty", "Попълни свободните"))
        self.fill_btn.setToolTip(tr("Gives free Note numbers (momentary) to every unassigned button in this layer.\n"
                                    "New layers are filled automatically (Settings turns that off).",
                                    "Дава свободни Note номера (momentary) на всички незададени бутони в този слой.\n"
                                    "Новите слоеве се попълват автоматично (изключва се от Настройки)."))
        self.fill_btn.clicked.connect(self.fill_layer)
        h.addWidget(self.fill_btn)
        self.clear_btn = QPushButton(tr("Clear layer", "Изчисти слоя"))
        self.clear_btn.clicked.connect(self.clear_layer)
        h.addWidget(self.clear_btn)
        self.layer_hint = QLabel()
        self.layer_hint.setObjectName("muted")
        h.addWidget(self.layer_hint, 1)
        return bar

    def _refresh_layers(self):
        layers = self.profile.reachable_layers()
        if self.edit_layer not in layers:
            self.edit_layer = ""
        self._known_layers = set(layers)
        if self._popover is not None and self.view.layer != self.edit_layer:
            try:
                self._popover.close()  # it edits a button of the layer that just went away
            except RuntimeError:
                pass
        self.pin_cb.blockSignals(True)
        self.pin_cb.setEnabled(len(layers) > 1)
        self.pin_cb.blockSignals(False)
        self.layer_combo.blockSignals(True)
        self.layer_combo.clear()
        for key in layers:
            n = sum(1 for b in BUTTON_IDS
                    if b not in layer_mods(key) and (m := self.profile.effective_map(key, b))
                    and m.enabled and m.action != "modifier")
            self.layer_combo.addItem(tr("{}   ({} buttons)", "{}   ({} бутона)").format(layer_label(key), n), key)
        self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(self.edit_layer)))
        self.layer_combo.blockSignals(False)
        self.clear_btn.setEnabled(bool(self.edit_layer))
        if len(layers) == 1:
            self.layer_hint.setText(tr("Set a button as “Modifier” to get new layers.",
                                       "Задай бутон като „Модификатор“, за да получиш нови слоеве."))
        else:
            self.layer_hint.setText(tr("{} layers · hold a modifier on the controller to see its layer",
                                       "{} слоя · задръж модификатор на контролера, за да видиш слоя му").format(len(layers)))
        self.view.layer = self.edit_layer
        self.view.update()

    def _select_layer(self, key: str):
        """Picked from the list: an explicit choice, so the layer stays until you pick another."""
        self.edit_layer = key or ""
        self._set_pin(bool(key))
        self._refresh_layers()

    def _set_pin(self, on: bool):
        self.pin_cb.blockSignals(True)
        self.pin_cb.setChecked(on)
        self.pin_cb.blockSignals(False)

    def _pin_toggled(self, on: bool):
        if not on:  # let go: follow the controller again (the layer held right now, or the base)
            self.edit_layer = self._live_layer
            self._refresh_layers()

    def _fillable_buttons(self) -> list[str]:
        """Buttons this controller has (and reports) that a new layer can give a Note to."""
        visible = set(self.view.visible_inputs())
        return [b for b in BUTTON_IDS
                if b in visible and not (b in unreliable_inputs() and b not in self.engine.seen)]

    @staticmethod
    def _slot_text(filled: list[tuple[str, int, int]]) -> str:
        notes = [n for _, _, n in filled]
        chans = sorted({c for _, c, _ in filled})
        text = f"Note {min(notes)}–{max(notes)}" if len(notes) > 1 else f"Note {notes[0]}"
        if chans != [1]:
            text += tr(" (channels {})", " (канали {})").format(", ".join(map(str, chans)))
        return text

    def fill_layer(self):
        key = self.edit_layer
        with self.engine.lock:
            filled = self.profile.fill_layer(key, self._fillable_buttons())
        self._save_timer.start()
        self._refresh_layers()
        self.statusBar().showMessage(
            tr("Filled {} buttons: {}", "Попълнени {} бутона: {}").format(len(filled), self._slot_text(filled))
            if filled else tr("No unassigned buttons in this layer.", "Няма незададени бутони в този слой."), 8000)

    def _autofill_new_layers(self):
        """A button just became a modifier: give the layers that appeared free Notes right away."""
        new = [k for k in self.profile.reachable_layers() if k not in self._known_layers]
        if not new or not self.profile.options.auto_fill_layers:
            return
        buttons = self._fillable_buttons()
        parts = []
        with self.engine.lock:
            for key in new:
                filled = self.profile.fill_layer(key, buttons)
                if filled:
                    parts.append(f"“{layer_label(key)}”: {len(filled)} ({self._slot_text(filled)})")
        if parts:
            self.statusBar().showMessage(
                tr("New layer filled with free Notes, change any of them if you like. ",
                   "Новият слой е попълнен със свободни Note номера, променяй ги свободно. ") + " · ".join(parts), 12000)

    def clear_layer(self):
        key = self.edit_layer
        if not key:
            return
        if QMessageBox.question(self, tr("Clear layer", "Изчисти слоя"),
                                tr("Delete all values in the layer “{}”?", "Да изтрия ли всички стойности в слоя „{}“?")
                                .format(layer_label(key))) != QMessageBox.Yes:
            return
        with self.engine.lock:
            self.profile.clear_layer(key)
        self.engine.refresh_axes()  # in case this layer is the one held right now
        self._save_timer.start()
        self._refresh_layers()

    def _axis_override(self, key: str, axis: str, own: bool):
        """Give an axis its own settings in layer `key` (a copy of what applies there now), or take them
        away again. Returns the settings that apply afterwards."""
        with self.engine.lock:
            if own:
                self.profile.ensure_axis_override(key, axis)
            else:
                self.profile.remove_axis_override(key, axis)
            m = self.profile.effective_axis(key, axis)
        self._save_timer.start()
        return m

    # ---------------------------------------------------------------- editing
    def open_editor(self, input_id: str, anchor=None):
        if self._popover is not None:
            try:
                self._popover.close()
            except RuntimeError:
                pass
        self.view.selected = input_id
        if anchor is None or anchor.isNull():
            anchor = self.view.label_global_rect(input_id)
        is_axis = input_id in AXIS_IDS
        key = self.edit_layer
        if not is_axis and input_id in layer_mods(key):
            self.view.selected = None
            self.statusBar().showMessage(
                tr("{} is the held modifier of the layer “{}”. Edit it in the lower layer.",
                   "{} е задържаният модификатор на слоя „{}“. Редактирай го в по-ниския слой.")
                .format(INPUT_LABELS[input_id], layer_label(key)), 6000)
            return
        if is_axis:
            m = self.profile.effective_axis(key, input_id)  # this layer's own settings, or the inherited ones
        elif key:
            with self.engine.lock:
                m = self.profile.ensure_button_map(key, input_id)
        else:
            m = self.profile.buttons[input_id]
        extra = {"seen": input_id in self.engine.seen,
                 "layer": key,
                 "axis_source": lambda: self.profile.axis_source(key, input_id),
                 "override_create": lambda: self._axis_override(key, input_id, True),
                 "override_remove": lambda: self._axis_override(key, input_id, False),
                 "usage": lambda kind, ch, excl: self.profile.usage(kind, ch, excl),
                 "inherited": not is_axis and self.profile.inherited_modifier(key, input_id),
                 "options": self.profile.options,
                 "options_changed": self._options_changed_in_popover,
                 "center_axis": lambda a: self.engine.set_axis_value(a, 0.5)}
        pop = MappingPopover(self, input_id, m, self._mapping_changed, extra)
        pop.destroyed.connect(lambda *_, p=pop: self._popover_closed(p))
        self._popover = pop
        pop.show_near(anchor, prefer_left=any(s.left for s in self.view.slots if s.input_id == input_id))

    def _options_changed_in_popover(self):
        g = self.settings_panel.glide
        g.blockSignals(True)
        g.setValue(self.profile.options.center_time)
        g.blockSignals(False)
        self._save_timer.start()

    def _popover_closed(self, pop):
        if pop is not self._popover:
            return  # an old panel closed after a new one opened
        self._popover = None
        self.view.selected = None
        self.view.update()

    def _mapping_changed(self, input_id: str):
        # The edit is already in the profile object; sync the engine without jumps.
        self.engine.mapping_changed(input_id)
        self._autofill_new_layers()
        self._refresh_layers()
        self._save_timer.start()

    def _learn_toggled(self, on: bool):
        with self.engine.lock:
            self.engine.learn = on
            self.engine.learned = None
        self.view.learn = on
        self.view.update()

    # ---------------------------------------------------------------- profiles
    def _reload_profiles(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItems(self.store.list_profiles())
        self.profile_combo.setCurrentText(self.profile.name)
        self.profile_combo.blockSignals(False)
        if hasattr(self, "layer_combo"):
            self._refresh_layers()

    def _activate(self, profile):
        self.edit_layer = ""
        self._set_pin(False)
        self.store.save_profile(self.profile)
        self.profile = profile
        self.engine.set_profile(profile)
        self.view.set_profile(profile)
        self.store.settings["active_profile"] = profile.name
        self.store.save_settings()
        sp = self.settings_panel
        for w, v in ((sp.fine, profile.options.fine_factor), (sp.rate, profile.options.max_rate_hz),
                     (sp.glide, profile.options.center_time)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        sp.led.blockSignals(True)
        sp.led.setChecked(profile.options.led_layers)
        sp.led.blockSignals(False)
        sp.auto_fill.blockSignals(True)
        sp.auto_fill.setChecked(profile.options.auto_fill_layers)
        sp.auto_fill.blockSignals(False)
        self._reload_profiles()

    def switch_profile(self, name: str):
        if name and name != self.profile.name:
            self._activate(self.store.load_profile(name))

    def _ask_name(self, title: str, default: str) -> str | None:
        name, ok = QInputDialog.getText(self, title, tr("Profile name:", "Име на профила:"), text=default)
        name = name.strip()
        if not ok or not name:
            return None
        if self.store.exists(name) and name != self.profile.name:
            QMessageBox.warning(self, title, tr("Profile “{}” already exists.", "Профил „{}“ вече съществува.").format(name))
            return None
        return name

    def new_profile(self):
        name = self._ask_name(tr("New profile", "Нов профил"), tr("New profile", "Нов профил"))
        if name:
            p = default_profile(name)
            self.store.save_profile(p)
            self._activate(p)

    def duplicate_profile(self):
        name = self._ask_name(tr("Duplicate profile", "Дублирай профил"),
                              tr("{} (copy)", "{} (копие)").format(self.profile.name))
        if name:
            p = self.profile.clone(name)
            self.store.save_profile(p)
            self._activate(p)

    def rename_profile(self):
        name = self._ask_name(tr("Rename profile", "Преименувай профил"), self.profile.name)
        if name and name != self.profile.name:
            self.store.rename_profile(self.profile, name)
            self.store.settings["active_profile"] = name
            self.store.save_settings()
            self._reload_profiles()

    def delete_profile(self):
        names = self.store.list_profiles()
        if len(names) <= 1:
            QMessageBox.information(self, tr("Delete profile", "Изтрий профил"),
                                    tr("This is the only profile.", "Това е единственият профил."))
            return
        if QMessageBox.question(self, tr("Delete profile", "Изтрий профил"),
                                tr("Delete profile “{}”?", "Да изтрия ли профил „{}“?")
                                .format(self.profile.name)) != QMessageBox.Yes:
            return
        self.store.delete_profile(self.profile.name)
        nxt = [n for n in self.store.list_profiles() if n != self.profile.name][0]
        p = self.store.load_profile(nxt)
        self.profile = p  # so the deleted one isn't written back
        self.engine.set_profile(p)
        self.view.set_profile(p)
        self.store.settings["active_profile"] = p.name
        self.store.save_settings()
        self._reload_profiles()

    def reset_profile(self):
        if QMessageBox.question(
                self, tr("Reset to default", "Върни по подразбиране"),
                tr("Reset all buttons and axes in “{}” to the default layout?",
                   "Да върна ли всички бутони и оси в „{}“ към разпределението по подразбиране?")
                .format(self.profile.name)) != QMessageBox.Yes:
            return
        p = default_profile(self.profile.name)
        self.store.save_profile(p)
        self.profile = p
        self._activate(p)

    # ---------------------------------------------------------------- loop
    def tick(self):
        eng = self.engine
        eng.app_active = QGuiApplication.applicationState() == Qt.ApplicationActive
        snap = eng.snapshot()
        with eng.lock:
            values = {a: eng.axis_value_01(a) for a in AXIS_IDS}
        self.view.learn = snap["learn"]
        if snap["connected"] and snap["info"] and snap["info"] != self._info_applied:
            self._info_applied = snap["info"]
            self._controller_info(snap["info"])
        newly_seen = (snap["seen"] & set(UNRELIABLE_INPUTS)) - self.view.seen_ever
        if newly_seen:
            self.view.seen_ever |= newly_seen
            self.store.settings["seen_inputs"] = sorted(self.view.seen_ever)
            self.store.save_settings()
        live = snap["layer"]
        if live != self._live_layer:
            self.edit_layer = displayed_layer(self.edit_layer, self.pin_cb.isChecked(), live, self._live_layer)
            self._live_layer = live
            self._refresh_layers()
        self.view.layer_live = bool(live) and live == self.edit_layer
        self.view.set_state(snap, values, snap["outputs"])

        if snap["learned"]:
            with eng.lock:
                eng.learned = None
            self.learn_btn.blockSignals(True)
            self.learn_btn.setChecked(False)
            self.learn_btn.blockSignals(False)
            self.view.learn = False
            self.raise_()
            self.activateWindow()
            iid, key = snap["learned"]
            if iid not in AXIS_IDS:
                self.edit_layer = key
                self._set_pin(bool(key))  # you picked it to edit it: keep it on screen
                self._refresh_layers()
            self.open_editor(iid)

        if snap["devices"] != self._devices_shown:
            self._devices_shown = snap["devices"]
            self.settings_panel.set_devices(snap["devices"], self.store.settings.get("controller"))

        self._update_status(snap)
        self.monitor.refresh()
        if self.tabs.currentWidget() is self.test:
            self.test.refresh()

        if eng.rate_dirty and time.time() - self._last_rate_save > 2.0:
            self._save_rate_values()

    def _update_status(self, snap):
        if snap["connected"]:
            self.st_ctrl.setText(f"<span style='color:{theme.OK}'>●</span> " +
                                 tr("Controller: {}", "Контролер: {}").format(snap["name"]))
        elif snap["error"]:
            self.st_ctrl.setText(f"<span style='color:{theme.ERR}'>●</span> {snap['error']}")
        else:
            self.st_ctrl.setText(f"<span style='color:{theme.ERR}'>●</span> " +
                                 tr("Controller: not connected", "Контролер: несвързан"))
        if self.midi.is_open:
            self.st_midi.setText(f"<span style='color:{theme.OK}'>●</span> MIDI: {self.midi.port_name}")
        else:
            self.st_midi.setText(f"<span style='color:{theme.ERR}'>●</span> MIDI: " + tr("closed", "затворен") +
                                 f"{' (' + self.midi.error + ')' if self.midi.error else ''}")
        if snap["background_ok"]:
            self.st_bg.setText(f"<span style='color:{theme.OK}'>●</span> " +
                              tr("Background mode: working", "Фонов режим: работи"))
        else:
            self.st_bg.setText(f"<span style='color:{theme.MUTED}'>●</span> " +
                               tr("Background mode: not verified yet (switch to Lightkey and move a stick)",
                                  "Фонов режим: още не е проверен (премини към Lightkey и мръдни стик)"))
        flags = []
        if snap["gyro"]:
            flags.append(tr("GYRO", "ЖИРО"))
        if snap["fine"]:
            flags.append(tr("FINE ×{:.2f}", "ФИНО ×{:.2f}").format(self.profile.options.fine_factor))
        self.st_fine.setText("  ·  ".join(flags))

    def _save_rate_values(self):
        with self.engine.lock:
            self.engine.rate_dirty = False
            values = {_slot_text(k): round(v, 5) for k, v in self.engine.slot_values.items()}
        self._last_rate_save = time.time()
        if self.store.settings.get("persist_rate_values"):
            self.store.settings["rate_slots"] = values
            self.store.settings.pop("rate_values", None)  # the old per-axis format
            self.store.save_settings()

    def closeEvent(self, e):
        self.timer.stop()
        self.engine.stop()
        self._save_rate_values()
        self.store.save_profile(self.profile)
        self.store.save_settings()
        self.reader.stop()
        self.midi.close()
        super().closeEvent(e)


def run_gui() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Xbox MIDI Bridge")
    theme.apply(app)
    w = MainWindow()
    w.show()
    return app.exec()
