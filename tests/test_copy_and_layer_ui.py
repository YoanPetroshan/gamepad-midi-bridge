"""Copy/paste of a button's settings, and an axis' own settings in a layer (the editor window)."""
import os
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mapping import ButtonMapping, default_profile, settings_to_text  # noqa: E402


def popover(profile, iid, layer="", on_change=None):
    from PySide6.QtWidgets import QWidget
    from ui.popover import MappingPopover
    key = layer
    m = profile.effective_axis(key, iid) if iid in profile.axes else (
        profile.ensure_button_map(key, iid) if key else profile.buttons[iid])

    def own(on):
        profile.ensure_axis_override(key, iid) if on else profile.remove_axis_override(key, iid)
        return profile.effective_axis(key, iid)

    extra = {"layer": key, "usage": lambda k, c, e: profile.usage(k, c, e),
             "axis_source": lambda: profile.axis_source(key, iid),
             "override_create": lambda: own(True), "override_remove": lambda: own(False)}
    parent = QWidget()  # must outlive the panel, or Qt deletes the panel with it
    pop = MappingPopover(parent, iid, m, on_change or (lambda _: None), extra)
    pop._keep_parent = parent
    return pop


class CopyPasteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def put(self, text):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)

    def test_copy_puts_all_settings_on_the_clipboard(self):
        from PySide6.QtGui import QGuiApplication
        p = default_profile()
        p.buttons["b"] = ButtonMapping(type="cc", mode="toggle", channel=5, number=88, value=64, label="Strobe")
        d = popover(p, "b")
        d.copy_btn.click()
        self.assertEqual(QGuiApplication.clipboard().text(), settings_to_text(p.buttons["b"]))
        self.assertIn('"number": 88', QGuiApplication.clipboard().text())

    def test_paste_copies_every_setting_into_another_button(self):
        p = default_profile()
        src = ButtonMapping(type="cc", mode="toggle", channel=5, number=88, value=64, label="Strobe")
        self.put(settings_to_text(src))
        changed = []
        d = popover(p, "a", on_change=changed.append)
        self.assertTrue(d.paste_btn.isEnabled())
        d.paste_btn.click()
        self.assertEqual(asdict(p.buttons["a"]), asdict(src))
        self.assertEqual(changed[-1], "a", "the app is told, so it saves and syncs")
        self.assertEqual(d.number.value(), 88, "the editor shows the pasted values")

    def test_paste_with_a_new_number_takes_the_next_free_one(self):
        p = default_profile()
        self.put(settings_to_text(p.buttons["b"]))  # Note 37
        d = popover(p, "a")
        d.paste_new_btn.click()
        n = p.buttons["a"].number
        self.assertGreaterEqual(n, 57)
        self.assertNotIn(n, {m.number for k, m in p.buttons.items() if k != "a" and m.type == "note"})
        self.assertEqual(p.buttons["a"].type, "note")

    def test_paste_is_off_when_the_clipboard_holds_something_else(self):
        self.put("hello, not settings")
        self.assertFalse(popover(default_profile(), "a").paste_btn.isEnabled())
        self.put(settings_to_text(default_profile().axes["leftx"]))  # axis settings can't go into a button
        self.assertFalse(popover(default_profile(), "a").paste_btn.isEnabled())

    def test_axis_settings_fit_the_axis_they_are_pasted_into(self):
        p = default_profile()
        self.put(settings_to_text(p.axes["leftx"]))  # a rate stick
        d = popover(p, "touchx")
        d.paste_btn.click()
        self.assertEqual(p.axes["touchx"].mode, "relative", "a touchpad drags instead of a speed")
        self.assertEqual(p.axes["touchx"].cc, 10)


class AxisOwnSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.p = default_profile()
        self.p.buttons["leftshoulder"].action = "modifier"

    def test_in_a_layer_the_axis_starts_read_only_and_follows_the_base(self):
        d = popover(self.p, "leftx", "leftshoulder")
        self.assertFalse(d.own.isChecked())
        self.assertFalse(d.amode.isEnabled(), "inherited settings are shown but not edited here")
        self.assertTrue(d.own_note.text(), "says where the settings come from")

    def test_ticking_gives_it_its_own_copy_that_can_differ(self):
        changed = []
        d = popover(self.p, "leftx", "leftshoulder", on_change=changed.append)
        d.own.setChecked(True)
        self.assertEqual(self.p.axis_source("leftshoulder", "leftx"), "leftshoulder")
        self.assertTrue(d.amode.isEnabled())
        self.assertEqual(d.amode.currentData(), "rate", "it starts as a copy of the base")
        d.amode.setCurrentIndex(d.amode.findData("absolute"))
        self.assertEqual(self.p.axis_layers["leftshoulder"]["leftx"].mode, "absolute")
        self.assertEqual(self.p.axes["leftx"].mode, "rate", "the base layer is not touched")
        self.assertIn("leftx", changed)

    def test_unticking_goes_back_to_the_base(self):
        d = popover(self.p, "leftx", "leftshoulder")
        d.own.setChecked(True)
        d.own.setChecked(False)
        self.assertIsNone(self.p.axis_source("leftshoulder", "leftx"))
        self.assertNotIn("leftshoulder", self.p.axis_layers)
        self.assertFalse(d.amode.isEnabled())

    def test_the_base_layer_has_no_such_checkbox(self):
        d = popover(self.p, "leftx", "")
        self.assertFalse(hasattr(d, "own"))
        self.assertTrue(d.amode.isEnabled())

    def test_diagram_says_where_the_settings_come_from(self):
        from ui.controller_view import ControllerView
        v = ControllerView()
        v.set_profile(self.p)
        v.layer = "leftshoulder"
        self.assertIsNone(self.p.axis_source(v.layer, "leftx"))
        self.p.ensure_axis_override("leftshoulder", "leftx").mode = "absolute"
        self.assertEqual(self.p.axis_source(v.layer, "leftx"), "leftshoulder")
        v.resize(1200, 800)
        v.grab()  # paints every label without errors, with and without an override


class SavedPositionsTest(unittest.TestCase):
    def test_key_round_trip(self):
        from ui.main_window import _parse_slot, _slot_text
        for slot in ((1, 10, False), (16, 31, True)):
            self.assertEqual(_parse_slot(_slot_text(slot)), slot)
        self.assertIsNone(_parse_slot("leftx"))


if __name__ == "__main__":
    unittest.main()
