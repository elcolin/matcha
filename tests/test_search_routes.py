import os
import secrets
import tempfile
import unittest

from werkzeug.datastructures import MultiDict

from app.config import Config
from app.search.routes import _filter, _refine, _sort


class FilterTagsTests(unittest.TestCase):
    def test_no_tag_filter_keeps_all_items(self):
        items = [{"tags": ["coffee"]}, {"tags": []}]

        self.assertEqual(_filter(items, MultiDict()), items)

    def test_keeps_only_items_matching_all_required_tags_case_insensitively(self):
        items = [
            {"id": 1, "tags": ["Coffee", "Travel"]},
            {"id": 2, "tags": ["coffee"]},
            {"id": 3, "tags": ["music"]},
        ]

        result = _filter(items, MultiDict({"tags": "Coffee,travel"}))

        self.assertEqual([i["id"] for i in result], [1])


class RefineTests(unittest.TestCase):
    def test_no_refine_args_keeps_all_items(self):
        items = [{"age": 20, "distance_km": 5, "popularity_score": 1, "shared_tags_count": 0}]

        self.assertEqual(_refine(items, MultiDict(), viewer_age=30), items)

    def test_age_gap_is_relative_to_viewer_and_drops_unknown_age(self):
        items = [{"id": 1, "age": 33}, {"id": 2, "age": 40}, {"id": 3, "age": None}]

        result = _refine(items, MultiDict({"age_gap": "3"}), viewer_age=30)

        self.assertEqual([i["id"] for i in result], [1])

    def test_age_gap_ignored_when_viewer_age_unknown(self):
        items = [{"id": 1, "age": 33}]

        self.assertEqual(_refine(items, MultiDict({"age_gap": "1"}), viewer_age=None), items)

    def test_max_distance_min_fame_and_min_shared_tags(self):
        items = [
            {"id": 1, "distance_km": 10, "popularity_score": 50, "shared_tags_count": 2},
            {"id": 2, "distance_km": 80, "popularity_score": 50, "shared_tags_count": 2},
            {"id": 3, "distance_km": 10, "popularity_score": 5, "shared_tags_count": 2},
            {"id": 4, "distance_km": 10, "popularity_score": 50, "shared_tags_count": 0},
        ]
        args = MultiDict({"max_distance": "50", "min_fame": "20", "min_shared_tags": "1"})

        self.assertEqual([i["id"] for i in _refine(items, args, viewer_age=None)], [1])

    def test_negative_values_are_ignored(self):
        items = [{"id": 1, "age": 50, "distance_km": 10, "popularity_score": 0, "shared_tags_count": 0}]
        args = MultiDict({"age_gap": "-1", "max_distance": "-5"})

        self.assertEqual(_refine(items, args, viewer_age=20), items)


class SortTests(unittest.TestCase):
    def test_smart_match_descending_keeps_best_matches_first(self):
        items = [{"id": 1}, {"id": 2}, {"id": 3}]

        for args in (MultiDict(), MultiDict({"sort_by": "smart", "order": "desc"})):
            self.assertEqual([i["id"] for i in _sort(list(items), args)], [1, 2, 3])

    def test_smart_match_ascending_reverses_ranking(self):
        items = [{"id": 1}, {"id": 2}, {"id": 3}]

        result = _sort(items, MultiDict({"sort_by": "smart", "order": "asc"}))

        self.assertEqual([i["id"] for i in result], [3, 2, 1])


class SearchRouteTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        Config.DATABASE_PATH = self.original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _create_user(self, username, age):
        from app.db import execute, query_one

        with self.app.app_context():
            execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (f"{username}@example.com", username, username.title(), "User", "hash"),
            )
            user_id = query_one("SELECT id FROM users WHERE username = ?", (username,))["id"]
            execute("INSERT INTO profiles (user_id, age) VALUES (?, ?)", (user_id, age))
        return user_id

    def _login_as(self, user_id):
        from app.db import execute

        token = secrets.token_hex(16)
        with self.app.app_context():
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (user_id, token),
            )
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["session_token"] = token

    def test_search_page_requires_login(self):
        response = self.client.get("/search")

        self.assertEqual(response.status_code, 401)

    def test_search_page_is_linked_from_home_and_filters_results(self):
        viewer_id = self._create_user("viewer", 28)
        matching_id = self._create_user("matching", 32)
        self._create_user("too_young", 25)
        self._login_as(viewer_id)

        home = self.client.get("/")
        home_html = home.get_data(as_text=True)
        self.assertEqual(home.status_code, 200)
        self.assertIn('href="/search"', home_html)
        self.assertIn("Search profiles", home_html)

        initial = self.client.get("/search")
        self.assertEqual(initial.status_code, 200)
        self.assertIn("Advanced search", initial.get_data(as_text=True))

        results = self.client.get("/search?min_age=30&sort_by=age&order=asc")
        html = results.get_data(as_text=True)
        self.assertEqual(results.status_code, 200)
        self.assertIn("Matching, 32", html)
        self.assertNotIn("Too_young, 25", html)
        self.assertIn(f'href="/profile/{matching_id}"', html)

    def test_search_can_sort_profiles_when_age_is_missing(self):
        viewer_id = self._create_user("viewer", 28)
        missing_age_id = self._create_user("missing_age", None)
        aged_id = self._create_user("aged", 32)
        self._login_as(viewer_id)

        ascending = self.client.get("/search?sort_by=age&order=asc")
        ascending_html = ascending.get_data(as_text=True)
        self.assertEqual(ascending.status_code, 200)
        self.assertLess(
            ascending_html.index(f'href="/profile/{missing_age_id}"'),
            ascending_html.index(f'href="/profile/{aged_id}"'),
        )

        descending = self.client.get("/search?sort_by=age&order=desc")
        descending_html = descending.get_data(as_text=True)
        self.assertEqual(descending.status_code, 200)
        self.assertLess(
            descending_html.index(f'href="/profile/{aged_id}"'),
            descending_html.index(f'href="/profile/{missing_age_id}"'),
        )

    def test_home_page_shows_sort_and_filter_form_without_ranges(self):
        viewer_id = self._create_user("viewer", 28)
        self._login_as(viewer_id)

        html = self.client.get("/").get_data(as_text=True)

        self.assertIn('action="/"', html)
        for field in ("age_gap", "max_distance", "min_fame", "min_shared_tags", "sort_by", "order"):
            self.assertIn(f'name="{field}"', html)
        for range_field in ("min_age", "max_age", "min_popularity", "max_popularity"):
            self.assertNotIn(f'name="{range_field}"', html)

    def test_search_page_keeps_range_criteria_and_result_filters(self):
        viewer_id = self._create_user("viewer", 28)
        self._login_as(viewer_id)

        html = self.client.get("/search").get_data(as_text=True)

        for field in ("min_age", "max_age", "min_popularity", "max_popularity", "city", "tags",
                      "age_gap", "max_distance", "min_fame", "min_shared_tags", "sort_by", "order"):
            self.assertIn(f'name="{field}"', html)

    def test_search_results_can_be_refined_by_age_gap(self):
        viewer_id = self._create_user("viewer", 30)
        close_id = self._create_user("close", 32)
        far_id = self._create_user("far", 45)
        self._login_as(viewer_id)

        html = self.client.get("/search?min_age=18&max_age=60&age_gap=5").get_data(as_text=True)

        self.assertIn(f'href="/profile/{close_id}"', html)
        self.assertNotIn(f'href="/profile/{far_id}"', html)

    def test_home_page_filters_suggestions_by_age_gap(self):
        viewer_id = self._create_user("viewer", 28)
        matching_id = self._create_user("matching", 32)
        too_young_id = self._create_user("too_young", 20)
        self._login_as(viewer_id)

        html = self.client.get("/?age_gap=5").get_data(as_text=True)

        self.assertIn(f'href="/profile/{matching_id}"', html)
        self.assertNotIn(f'href="/profile/{too_young_id}"', html)

    def test_home_page_sorts_suggestions_by_age(self):
        viewer_id = self._create_user("viewer", 28)
        older_id = self._create_user("older", 40)
        younger_id = self._create_user("younger", 22)
        self._login_as(viewer_id)

        asc = self.client.get("/?sort_by=age&order=asc").get_data(as_text=True)
        self.assertLess(asc.index(f'href="/profile/{younger_id}"'), asc.index(f'href="/profile/{older_id}"'))

        desc = self.client.get("/?sort_by=age&order=desc").get_data(as_text=True)
        self.assertLess(desc.index(f'href="/profile/{older_id}"'), desc.index(f'href="/profile/{younger_id}"'))

    def test_home_page_shows_empty_message_when_no_profile_matches(self):
        viewer_id = self._create_user("viewer", 28)
        self._create_user("other", 30)
        self._login_as(viewer_id)

        html = self.client.get("/?min_fame=1000").get_data(as_text=True)

        self.assertIn("No profiles match your filters.", html)
        self.assertIn('href="/">Clear filters</a>', html)

    def test_home_page_without_filters_shows_no_suggestions_message(self):
        viewer_id = self._create_user("viewer", 28)
        self._login_as(viewer_id)

        html = self.client.get("/").get_data(as_text=True)

        self.assertIn("No suggestions for now.", html)
        self.assertNotIn("No profiles match your filters.", html)

    def test_search_page_shows_order_options_without_unknown_sort(self):
        viewer_id = self._create_user("viewer", 28)
        self._login_as(viewer_id)

        response = self.client.get("/search?sort_by=bogus&order=bogus")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
