import os
import tempfile
import unittest

from app.config import Config


class FlashMessageEscapingTests(unittest.TestCase):
    """Regression test for GitHub issue #42.

    Flash messages must always be HTML-escaped when rendered by
    app/templates/components/base.html: a `flash()` call can end up carrying
    user-controlled text (e.g. an APIError message built from form input), so
    the template must never disable Jinja2 autoescaping (`| safe`) on it.
    """

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def test_flash_message_is_html_escaped_on_render(self):
        payload = "<img src=x onerror=alert(document.cookie)>"

        with self.client.session_transaction() as sess:
            sess["_flashes"] = [("error", payload)]

        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertNotIn(payload, html)
        self.assertIn(
            "&lt;img src=x onerror=alert(document.cookie)&gt;", html
        )


if __name__ == "__main__":
    unittest.main()
