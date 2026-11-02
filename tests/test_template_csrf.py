"""Static checks on app/templates: every state-changing request must carry a CSRF token.

`csrf_protect()` (app/utils.py) rejects any POST/PUT/PATCH/DELETE without a valid
token, so a template that forgets it produces a silent 403 in the browser.
"""

import re
import unittest
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"

FORM_RE = re.compile(r"<form\b(?P<attrs>[^>]*)>(?P<body>.*?)</form>", re.IGNORECASE | re.DOTALL)
POST_METHOD_RE = re.compile(r"""\bmethod\s*=\s*["']?post\b""", re.IGNORECASE)
CSRF_INPUT_RE = re.compile(r"""name\s*=\s*["']csrf_token["']""", re.IGNORECASE)
UNSAFE_FETCH_METHOD_RE = re.compile(r"""\bmethod\s*:\s*["'`](POST|PUT|PATCH|DELETE)["'`]""", re.IGNORECASE)
CSRF_HEADER = "X-CSRFToken"


def _iter_templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def _line_of(text, index):
    return text.count("\n", 0, index) + 1


def post_forms_missing_csrf(text):
    """Return start offsets of `<form method="post">` blocks lacking a csrf_token input."""
    return [
        m.start()
        for m in FORM_RE.finditer(text)
        if POST_METHOD_RE.search(m.group("attrs")) and not CSRF_INPUT_RE.search(m.group("body"))
    ]


def _fetch_call_args(text, open_paren):
    """Return the argument source of the call whose `(` is at `open_paren`, balancing
    parentheses and skipping string/template literals so URLs like
    `fetch(partnerUrl(CHAT_PRESENCE_URL), {...})` are captured whole."""
    depth = 0
    quote = None
    i = open_paren
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1 : i]
        i += 1
    return text[open_paren + 1 :]


def unsafe_fetches_missing_csrf(text):
    """Return start offsets of `fetch(...)` calls using an unsafe method without X-CSRFToken."""
    missing = []
    for m in re.finditer(r"\bfetch\s*\(", text):
        args = _fetch_call_args(text, m.end() - 1)
        if UNSAFE_FETCH_METHOD_RE.search(args) and CSRF_HEADER not in args:
            missing.append(m.start())
    return missing


class TemplateCsrfDetectorTests(unittest.TestCase):
    """Sanity checks on the detectors themselves, so the template scan can't pass vacuously."""

    def test_multiline_uppercase_post_form_without_token_is_flagged(self):
        html = '<form\n  method="POST"\n  action="/x">\n<button>Go</button>\n</form>'
        self.assertEqual(len(post_forms_missing_csrf(html)), 1)

    def test_post_form_with_token_is_not_flagged(self):
        html = '<form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token() }}"></form>'
        self.assertEqual(post_forms_missing_csrf(html), [])

    def test_get_form_is_not_flagged(self):
        self.assertEqual(post_forms_missing_csrf('<form method="get"></form>'), [])

    def test_post_fetch_without_header_is_flagged(self):
        js = "fetch(`/chat/${id}/presence`, { method: 'POST' });"
        self.assertEqual(len(unsafe_fetches_missing_csrf(js)), 1)

    def test_post_fetch_with_nested_call_url_and_header_is_not_flagged(self):
        js = "fetch(partnerUrl(CHAT_PRESENCE_URL), { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });"
        self.assertEqual(unsafe_fetches_missing_csrf(js), [])

    def test_post_fetch_with_nested_call_url_without_header_is_flagged(self):
        js = "fetch(partnerUrl(CHAT_PRESENCE_URL), { method: 'POST' });"
        self.assertEqual(len(unsafe_fetches_missing_csrf(js)), 1)

    def test_get_fetch_is_not_flagged(self):
        self.assertEqual(unsafe_fetches_missing_csrf("fetch('/notifications/unread-count');"), [])


class TemplateCsrfScanTests(unittest.TestCase):
    def test_templates_directory_is_not_empty(self):
        self.assertTrue(_iter_templates())

    def test_every_post_form_includes_csrf_token(self):
        offenders = []
        for path in _iter_templates():
            text = path.read_text(encoding="utf-8")
            for offset in post_forms_missing_csrf(text):
                offenders.append(f"{path.relative_to(TEMPLATES_DIR)}:{_line_of(text, offset)}")
        self.assertEqual(offenders, [], "POST forms missing a csrf_token hidden input")

    def test_every_unsafe_fetch_sends_csrf_header(self):
        offenders = []
        for path in _iter_templates():
            text = path.read_text(encoding="utf-8")
            for offset in unsafe_fetches_missing_csrf(text):
                offenders.append(f"{path.relative_to(TEMPLATES_DIR)}:{_line_of(text, offset)}")
        self.assertEqual(offenders, [], "unsafe fetch() calls missing the X-CSRFToken header")


if __name__ == "__main__":
    unittest.main()
