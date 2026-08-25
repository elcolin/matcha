import unittest
from unittest.mock import patch

from flask import Flask

from app.routes import main_bp


class MainRoutesTests(unittest.TestCase):
    def test_home_maps_profiles_and_applies_default_image(self):
        app = Flask(__name__)
        app.register_blueprint(main_bp)

        rows = [
            {
                "id": 2,
                "name": "alice",
                "age": 25,
                "city": "Paris",
                "bio": "bio a",
                "image": "",
            },
            {
                "id": 1,
                "name": "bob",
                "age": 27,
                "city": "Lyon",
                "bio": "bio b",
                "image": "https://example.com/bob.jpg",
            },
        ]

        with patch("app.routes.query_all", return_value=rows) as mock_query_all, patch(
            "app.routes.render_template", return_value="rendered"
        ) as mock_render_template:
            with app.test_request_context("/"):
                response = app.view_functions["main.home"]()

        self.assertEqual(response, "rendered")
        self.assertEqual(mock_query_all.call_count, 1)
        query = mock_query_all.call_args.args[0]
        self.assertIn("FROM users u", query)
        self.assertIn("LIMIT 12", query)

        self.assertEqual(mock_render_template.call_count, 1)
        self.assertEqual(mock_render_template.call_args.args[0], "index.html")
        kwargs = mock_render_template.call_args.kwargs
        self.assertEqual(kwargs["name"], "Matcha User")
        self.assertEqual(len(kwargs["profiles"]), 2)
        self.assertEqual(
            kwargs["profiles"][0]["image"],
            "https://placehold.co/600x400?text=Matcha",
        )
        self.assertEqual(kwargs["profiles"][1]["image"], "https://example.com/bob.jpg")
        self.assertEqual(kwargs["profiles"][0]["interests"], [])

    def test_home_returns_empty_profiles_when_query_is_empty(self):
        app = Flask(__name__)
        app.register_blueprint(main_bp)

        with patch("app.routes.query_all", return_value=[]), patch(
            "app.routes.render_template", return_value="rendered-empty"
        ) as mock_render_template:
            with app.test_request_context("/"):
                response = app.view_functions["main.home"]()

        self.assertEqual(response, "rendered-empty")
        kwargs = mock_render_template.call_args.kwargs
        self.assertEqual(kwargs["profiles"], [])


if __name__ == "__main__":
    unittest.main()
