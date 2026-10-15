"""Layer bookkeeping and the number fields of the editor: python -m unittest discover tests"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mapping import BUTTON_IDS, ButtonMapping, default_profile  # noqa: E402


class FillAndUsageTest(unittest.TestCase):
    def setUp(self):
        self.p = default_profile()
        self.p.buttons["leftshoulder"].action = "modifier"
        self.buttons = [b for b in BUTTON_IDS if b not in ("guide", "misc1")]

    def test_new_layer_gets_unique_free_notes(self):
        filled = self.p.fill_layer("leftshoulder", self.buttons)
        notes = [(c, n) for _, c, n in filled]
        self.assertEqual(len(filled), len(self.buttons) - 1, "every button except the modifier itself")
        self.assertEqual(len(set(notes)), len(notes), "no duplicates")
        base = {m.number for m in self.p.buttons.values() if m.action == "midi"}
        self.assertFalse({n for c, n in notes if c == 1} & base, "must avoid notes the base layer uses")
        self.assertEqual(self.p.fill_layer("leftshoulder", self.buttons), [], "second run: nothing left")

    def test_fill_keeps_what_the_user_set_and_inherited_modifiers(self):
        self.p.buttons["dpup"].action = "modifier"
        self.p.layers["leftshoulder"] = {"x": ButtonMapping(type="cc", number=53)}
        filled = {b for b, _, _ in self.p.fill_layer("leftshoulder", self.buttons)}
        self.assertNotIn("x", filled)
        self.assertNotIn("dpup", filled, "an inherited modifier is not a button to fill")
        self.assertEqual(self.p.layers["leftshoulder"]["x"].number, 53)

    def test_channels_roll_over_instead_of_duplicating(self):
        # every note of channel 1 is taken (spread over the base and one layer)
        self.p.layers["leftshoulder"] = {f"k{n}": ButtonMapping(number=n) for n in range(128)}
        ch, n = self.p.free_slot()
        self.assertEqual(ch, 2)

    def test_usage_names_button_and_layer_and_excludes_itself(self):
        who = self.p.usage("note", 1)
        self.assertEqual(who[36], ["A · Base"] if __import__("i18n").LANG == "en" else ["A · Основен"])
        self.p.layers["leftshoulder"] = {"x": ButtonMapping(number=36)}
        self.assertEqual(len(self.p.usage("note", 1)[36]), 2)
        self.assertEqual(len(self.p.usage("note", 1, exclude=("leftshoulder", "x"))[36]), 1)
        self.assertNotIn(36, self.p.usage("cc", 1), "notes and CCs are separate")
        self.assertNotIn(36, self.p.usage("note", 2), "other channel")

    def test_usage_includes_axes_for_cc(self):
        who = self.p.usage("cc", 1)
        self.assertTrue(any("Left stick X" in w for w in who[10]))
        self.p.axes["leftx"].hires = True
        self.assertIn(42, self.p.usage("cc", 1), "the LSB of a 14-bit axis is taken too")


class LayerFollowTest(unittest.TestCase):
    def test_hold_shows_layer_and_release_returns_to_base(self):
        from ui.main_window import displayed_layer
        self.assertEqual(displayed_layer("", False, "leftshoulder", ""), "leftshoulder")
        self.assertEqual(displayed_layer("leftshoulder", False, "", "leftshoulder"), "")

    def test_pinned_layer_stays_after_release(self):
        from ui.main_window import displayed_layer
        self.assertEqual(displayed_layer("leftshoulder", True, "", "leftshoulder"), "leftshoulder")

    def test_releasing_one_of_two_modifiers_shows_the_remaining_layer(self):
        from ui.main_window import displayed_layer
        self.assertEqual(displayed_layer("leftshoulder+dpup", False, "leftshoulder", "leftshoulder+dpup"),
                         "leftshoulder")

    def test_nothing_changes_while_the_held_layer_is_unchanged(self):
        from ui.main_window import displayed_layer
        self.assertEqual(displayed_layer("rightshoulder", True, "", ""), "rightshoulder",
                         "a layer picked from the list is not touched while nothing is held")


class ValueBoxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_typing_a_number_applies_it(self):
        from ui.valuebox import ValueBox
        box, got = ValueBox(0, 127), []
        box.valueChanged.connect(got.append)
        box.lineEdit().textEdited.emit("64")
        self.assertEqual((box.value(), got), (64, [64]))
        box.lineEdit().textEdited.emit("300")  # out of range: ignored
        self.assertEqual(box.value(), 64)

    def test_picking_from_the_list_shows_just_the_number(self):
        from ui.valuebox import ValueBox
        box, got = ValueBox(0, 127, describe=lambda n: "C1"), []
        box.valueChanged.connect(got.append)
        self.assertIn("C1", box.itemText(36))
        box.activated.emit(36)
        self.assertEqual((box.value(), box.lineEdit().text(), got), (36, "36", [36]))

    def test_set_value_is_silent(self):
        from ui.valuebox import ValueBox
        box, got = ValueBox(1, 16), []
        box.valueChanged.connect(got.append)
        box.setValue(9)
        self.assertEqual((box.value(), got), (9, []))

    def test_list_marks_used_values_with_their_owner(self):
        from ui.valuebox import ValueBox
        owners = {36: ["A · Base"], 37: ["B · Base", "X · LB"]}
        box = ValueBox(0, 127, owners=lambda: owners)
        box._rebuild()
        self.assertIn("←   A · Base", box.itemText(36))
        self.assertIn("+1", box.itemText(37))
        self.assertNotIn("←", box.itemText(38))

    def test_popover_has_no_spin_arrows(self):
        from PySide6.QtWidgets import QAbstractSpinBox, QWidget
        from ui.popover import MappingPopover
        from ui.valuebox import ValueBox
        p = default_profile()
        parent = QWidget()
        for iid, m in (("a", p.buttons["a"]), ("leftx", p.axes["leftx"])):
            pop = MappingPopover(parent, iid, m, lambda _: None,
                                 {"usage": lambda k, c, e: p.usage(k, c, e), "layer": ""})
            for spin in pop.findChildren(QAbstractSpinBox):
                self.assertEqual(spin.buttonSymbols(), QAbstractSpinBox.NoButtons)
            self.assertTrue(pop.findChildren(ValueBox))
        pop = MappingPopover(parent, "b", p.buttons["b"], lambda _: None,
                             {"usage": lambda k, c, e: p.usage(k, c, e), "layer": ""})
        pop.number._rebuild()
        self.assertIn("←", pop.number.itemText(36), "note 36 belongs to A")
        self.assertNotIn("←", pop.number.itemText(37), "note 37 is B itself")


if __name__ == "__main__":
    unittest.main()
