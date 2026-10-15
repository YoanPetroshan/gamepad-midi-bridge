"""Feedback links and the About / feedback windows: python -m unittest discover tests"""
import os
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import feedback  # noqa: E402


class UrlTest(unittest.TestCase):
    def test_fields_are_filled_in(self):
        info = feedback.system_info("Xbox Series X Controller", "xbox", "bg")
        url, cut = feedback.build_issue_url("idea", "Tap  tempo", "A button & more: 100%", info)
        q = parse_qs(urlparse(url).query)
        self.assertFalse(cut)
        self.assertTrue(url.startswith("https://github.com/YoanPetroshan/gamepad-midi-bridge/issues/new?"))
        self.assertEqual(q["template"], ["feature_request.yml"])
        self.assertEqual(q["title"], ["[Idea] Tap tempo"])
        self.assertEqual(q["idea"], ["A button & more: 100%"], "special characters survive")
        self.assertIn("Xbox Series X Controller", q["app_info"][0])

    def test_each_kind_uses_its_own_form_and_field(self):
        for kind, tpl, field in (("bug", "bug_report.yml", "what"), ("other", "question.yml", "message")):
            q = parse_qs(urlparse(feedback.build_issue_url(kind, "t", "text")[0]).query)
            self.assertEqual((q["template"], q[field]), ([tpl], ["text"]))

    def test_info_is_optional(self):
        q = parse_qs(urlparse(feedback.build_issue_url("idea", "t", "x", None)[0]).query)
        self.assertNotIn("app_info", q)

    def test_very_long_text_is_cut_to_fit_and_flagged(self):
        url, cut = feedback.build_issue_url("bug", "Long", "word " * 5000, feedback.system_info())
        self.assertTrue(cut)
        self.assertLessEqual(len(url), feedback.MAX_URL)
        self.assertIn("app_info", parse_qs(urlparse(url).query), "the technical info is never the part that is cut")

    def test_info_has_no_personal_data(self):
        info = feedback.system_info("Pad", "xbox", "en")
        for secret in (os.path.expanduser("~"), os.environ.get("USER", "\0")):
            self.assertNotIn(secret, info)
        self.assertIn("macOS", info)


class FormsMatchCodeTest(unittest.TestCase):
    def test_every_field_the_app_fills_exists_in_its_form(self):
        for kind in feedback.KINDS.values():
            text = (ROOT / ".github" / "ISSUE_TEMPLATE" / kind.template).read_text()
            for field in (kind.field, "app_info"):
                self.assertRegex(text, rf"(?m)^\s+id:\s*{field}\s*$", f"{kind.template} lacks id {field}")
            self.assertIn(f'title: "{kind.prefix}"', text)


class WindowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_about_shows_the_version_and_its_buttons_work(self):
        from version import APP_VERSION
        from ui.about_dialog import AboutDialog
        calls = []
        d = AboutDialog(None, lambda: calls.append("check"), lambda: calls.append("news"),
                        lambda: calls.append("feedback"), lambda: "Xbox MIDI Bridge test")
        self.assertIn(APP_VERSION, d.version_label.text())
        d.check_btn.click(); d.news_btn.click(); d.feedback_btn.click()
        self.assertEqual(calls, ["check", "news", "feedback"])
        self.assertEqual(d.info_box.toPlainText(), "Xbox MIDI Bridge test")

    def test_feedback_window_builds_the_link_from_what_was_typed(self):
        from ui.about_dialog import FeedbackDialog
        d = FeedbackDialog(None, lambda: "INFO")
        d.kind.setCurrentIndex(d.kind.findData("bug"))
        d.title.setText("It crashes")
        d.details.setPlainText("When I press LB")
        q = parse_qs(urlparse(d.url()[0]).query)
        self.assertEqual((q["template"], q["title"], q["what"], q["app_info"]),
                         (["bug_report.yml"], ["[Bug] It crashes"], ["When I press LB"], ["INFO"]))
        d.include.setChecked(False)
        self.assertNotIn("app_info", parse_qs(urlparse(d.url()[0]).query), "unticked: nothing technical goes along")

    def test_empty_feedback_is_not_sent(self):
        from ui import about_dialog
        from ui.about_dialog import FeedbackDialog
        opened = []
        real = about_dialog.open_url
        about_dialog.open_url = opened.append
        try:
            d = FeedbackDialog(None, lambda: "INFO")
            d.send_btn.click()
            self.assertEqual(opened, [])
            d.title.setText("x")
            d.send_btn.click()
            self.assertEqual(len(opened), 1)
        finally:
            about_dialog.open_url = real


if __name__ == "__main__":
    unittest.main()
