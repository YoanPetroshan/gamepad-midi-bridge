"""Feedback: build a pre-filled GitHub issue from the text the user wrote in the app.

Nothing is sent by the app itself. It opens the browser on GitHub's "new issue" form with the
text already filled in; the person reads it and presses "Submit" with their own GitHub account.
The issue forms live in .github/ISSUE_TEMPLATE/ (field ids: idea/why, what/steps, message, app_info).
"""
from __future__ import annotations

import platform
from dataclasses import dataclass
from urllib.parse import quote_plus

from updater import REPO
from version import APP_VERSION

ISSUES_URL = f"https://github.com/{REPO}/issues"
WISHES_URL = f"https://github.com/{REPO}/issues?q=is%3Aissue+is%3Aopen+label%3Aenhancement+sort%3Areactions-%2B1-desc"
REPO_URL = f"https://github.com/{REPO}"
MAX_URL = 6500  # browsers and GitHub cope with ~8000; stay well below


@dataclass(frozen=True)
class Kind:
    key: str
    template: str  # file name in .github/ISSUE_TEMPLATE/
    prefix: str  # start of the issue title
    field: str  # id of the main text field in the form


KINDS = {
    "idea": Kind("idea", "feature_request.yml", "[Idea] ", "idea"),
    "bug": Kind("bug", "bug_report.yml", "[Bug] ", "what"),
    "other": Kind("other", "question.yml", "[Feedback] ", "message"),
}


def system_info(controller: str | None = None, family: str | None = None, language: str | None = None) -> str:
    """What the person agrees to share. Technical only: no names, paths, MIDI data or profiles."""
    mac = platform.mac_ver()[0] or platform.platform()
    lines = [f"Xbox MIDI Bridge {APP_VERSION}",
             f"macOS {mac} ({platform.machine()})",
             f"Controller: {controller or 'none connected'}" + (f" [{family}]" if controller and family else ""),
             f"Language: {language or '?'}"]
    return "\n".join(lines)


def build_issue_url(kind: str, title: str, details: str, info: str | None = None) -> tuple[str, bool]:
    """(URL, shortened). `shortened` is True when the text had to be cut to fit into a link; the
    caller should then put the full text on the clipboard."""
    k = KINDS[kind]
    title = " ".join(title.split())[:120]

    def url(text: str) -> str:
        q = [("template", k.template), ("title", (k.prefix + title).strip())]
        if text.strip():
            q.append((k.field, text.strip()))
        if info:
            q.append(("app_info", info))
        return f"{ISSUES_URL}/new?" + "&".join(f"{n}={quote_plus(v)}" for n, v in q)

    full = url(details)
    if len(full) <= MAX_URL:
        return full, False
    lo, hi = 0, len(details)  # longest prefix of the text that still fits
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(url(details[:mid] + " …")) <= MAX_URL:
            lo = mid
        else:
            hi = mid - 1
    return url(details[:lo] + " …"), True
