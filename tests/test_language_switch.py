"""Switching the language while the app runs must not interrupt anything.

Runs the real main window in a child process with its own HOME (so the real settings are never
touched), offscreen, with no controller attached: python -m unittest discover tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r'''
import sys, os, json, time
sys.path.insert(0, os.getcwd())
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton
import i18n
from ui import theme
from ui.main_window import MainWindow
from mapping import BUTTON_IDS, AXIS_IDS

app = QApplication(sys.argv); theme.apply(app)
w = MainWindow(); w.resize(1400, 860); w.show()
w.reader.stop(); w.engine.reader = None
eng, midi, store_id, t = w.engine, w.midi, id(w.store), [0.0]
out = {}

def state(*held):
    return ("state", tuple(b in held for b in BUTTON_IDS), tuple(0.0 for _ in AXIS_IDS), False)

def step(msg=None, n=30):
    if msg: eng.feed(msg, t[0])
    for _ in range(n):
        t[0] += 0.004; eng.step(t[0])
    w.tick()

def texts():
    return {"lang": i18n.LANG, "tabs": [w.tabs.tabText(i) for i in range(w.tabs.count())],
            "lang_btn": w.lang_btn.text(), "pin": w.pin_cb.text(), "center": w.center_btn.text(),
            "label_a": __import__("mapping").INPUT_LABELS["touchx"]}

def pump(ms, then):
    QTimer.singleShot(ms, then)

def run():
    w.profile.buttons["leftshoulder"].action = "modifier"
    w._mapping_changed("leftshoulder")
    eng.feed(("connected", "Xbox", {}, {"family": "xbox"}), t[0]); step(state(), 80)
    w.tabs.setCurrentIndex(2)                        # Settings tab
    w._select_layer("leftshoulder")                  # looking at the LB layer, pinned
    w.show_about(); out["about_open"] = w._about.isVisible(); out["about_before"] = w.st_about.toolTip()
    out["before"] = texts()
    out["before"].update(sent=midi.sent_count, thread=eng._thread.is_alive(), tab=w.tabs.currentIndex())
    step(state("a")); step(state())                  # a Note On/Off before the switch
    sent1 = midi.sent_count
    w.switch_language("bg"); pump(50, after_bg)
    out["sent_before_switch"] = sent1

def after_bg():
    out["bg"] = texts()
    out["bg"].update(thread=eng._thread.is_alive(), tab=w.tabs.currentIndex(), layer=w.view.layer,
                     pinned=w.pin_cb.isChecked(), same_engine=(w.engine is eng), same_midi=(w.midi is midi),
                     same_store=(id(w.store) == store_id))
    out["about_after_rebuild"] = w._about is None    # the old-language window was closed
    out["about_after"] = w.st_about.toolTip(); out["version_btn"] = w.st_about.text()
    step(state("a")); step(state())                  # still sends right after the switch
    out["bg"]["sent_after"] = midi.sent_count
    out["bg"]["monitor_rows"] = w.monitor.text.document().blockCount()
    w.switch_language("en"); pump(50, after_en)

def after_en():
    step(state("a")); step(state())                  # and again after switching back
    out["en"] = texts()
    out["en"].update(thread=eng._thread.is_alive(), sent_after=midi.sent_count)
    out["settings"] = json.load(open(os.path.join(os.environ["HOME"], "Library/Application Support/XboxMidiBridge/settings.json")))["language"]
    out["quit_actions"] = sum(1 for a in w.actions() if a.shortcut().toString() in ("Ctrl+Q", "Meta+Q"))
    print("RESULT" + json.dumps(out)); w.close(); app.quit()

QTimer.singleShot(400, run); app.exec()
'''


class LanguageSwitchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        home = tempfile.mkdtemp()
        cfg = Path(home) / "Library/Application Support/XboxMidiBridge"
        cfg.mkdir(parents=True)
        (cfg / "settings.json").write_text(json.dumps({"language": "en", "last_seen_version": "99.0.0",
                                                       "auto_update_check": False}))
        env = dict(os.environ, HOME=home, QT_QPA_PLATFORM="offscreen")
        env.pop("XMB_LANG", None)
        r = subprocess.run([sys.executable, "-c", CHILD], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), None)
        if line is None:
            raise AssertionError("the window did not finish:\n" + r.stdout[-1500:] + r.stderr[-2500:])
        cls.out = json.loads(line[len("RESULT"):])

    def test_texts_change_both_ways(self):
        o = self.out
        self.assertEqual(o["before"]["lang"], "en")
        self.assertEqual(o["before"]["tabs"], ["MIDI monitor", "Lightkey test", "Settings"])
        self.assertEqual(o["bg"]["tabs"], ["MIDI монитор", "Тест за Lightkey", "Настройки"])
        self.assertEqual(o["bg"]["pin"], "Задръж слоя")
        self.assertEqual(o["bg"]["label_a"], "Тъчпад X", "input names follow the language too")
        self.assertEqual(o["en"]["tabs"], o["before"]["tabs"])
        self.assertEqual(o["en"]["center"], "Center Pan/Tilt")

    def test_language_button_offers_the_other_language(self):
        self.assertIn("BG", self.out["before"]["lang_btn"])
        self.assertIn("EN", self.out["bg"]["lang_btn"])

    def test_nothing_is_interrupted(self):
        o = self.out
        self.assertTrue(o["before"]["thread"] and o["bg"]["thread"] and o["en"]["thread"], "engine thread keeps running")
        self.assertTrue(o["bg"]["same_engine"] and o["bg"]["same_midi"] and o["bg"]["same_store"],
                        "the same engine, MIDI port and store: no restart")
        self.assertGreater(o["bg"]["sent_after"], o["sent_before_switch"], "MIDI is sent right after the switch")
        self.assertGreater(o["en"]["sent_after"], o["bg"]["sent_after"])

    def test_view_state_is_kept(self):
        o = self.out
        self.assertEqual(o["bg"]["tab"], o["before"]["tab"], "same tab")
        self.assertEqual(o["bg"]["layer"], "leftshoulder", "same layer on screen")
        self.assertTrue(o["bg"]["pinned"], "a layer picked from the list stays pinned")

    def test_version_button_follows_the_language_and_old_about_window_closes(self):
        from version import APP_VERSION
        o = self.out
        self.assertTrue(o["about_open"])
        self.assertTrue(o["about_after_rebuild"])
        self.assertIn(APP_VERSION, o["version_btn"])
        self.assertNotEqual(o["about_before"], o["about_after"], "the tooltip changed language")

    def test_choice_is_saved_and_history_kept(self):
        self.assertEqual(self.out["settings"], "en")
        self.assertGreater(self.out["bg"]["monitor_rows"], 1, "the MIDI monitor history is still there")
        self.assertEqual(self.out["quit_actions"], 1, "one Quit shortcut, not one per rebuild")


if __name__ == "__main__":
    unittest.main()
