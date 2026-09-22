import unittest

from app.db import execute
from app.match.routes import (
    apply_filters,
    apply_sort,
    calculate_distance,
    candidate_profiles,
    is_gender_compatible,
    shared_tag_count,
)
from tests.helpers import DBTestCase


class CalculateDistanceTests(unittest.TestCase):
    def test_returns_sentinel_when_any_coordinate_is_missing(self):
        self.assertEqual(calculate_distance(None, 1.0, 2.0, 3.0), 99999.0)
        self.assertEqual(calculate_distance(1.0, None, 2.0, 3.0), 99999.0)
        self.assertEqual(calculate_distance(1.0, 2.0, None, 3.0), 99999.0)
        self.assertEqual(calculate_distance(1.0, 2.0, 3.0, None), 99999.0)

    def test_computes_manhattan_like_distance_in_km(self):
        # 1 degree ~= 111km on both axes in this simplified model
        distance = calculate_distance(48.0, 2.0, 49.0, 3.0)

        self.assertAlmostEqual(distance, 222.0)

    def test_zero_distance_for_identical_coordinates(self):
        self.assertEqual(calculate_distance(48.85, 2.35, 48.85, 2.35), 0.0)


class IsGenderCompatibleTests(unittest.TestCase):
    def test_everyone_preference_accepts_any_gender(self):
        self.assertTrue(is_gender_compatible("everyone", "male"))
        self.assertTrue(is_gender_compatible("everyone", "female"))
        self.assertTrue(is_gender_compatible("everyone", None))

    def test_men_preference_only_accepts_male(self):
        self.assertTrue(is_gender_compatible("men", "male"))
        self.assertFalse(is_gender_compatible("men", "female"))
        self.assertFalse(is_gender_compatible("men", "non-binary"))

    def test_women_preference_only_accepts_female(self):
        self.assertTrue(is_gender_compatible("women", "female"))
        self.assertFalse(is_gender_compatible("women", "male"))

    def test_unknown_preference_defaults_to_permissive(self):
        self.assertTrue(is_gender_compatible("unexpected", "male"))


class ApplyFiltersTests(unittest.TestCase):
    def test_no_tag_filter_keeps_all_items(self):
        items = [{"tags": ["coffee"]}, {"tags": []}]

        self.assertEqual(apply_filters(items, {}), items)

    def test_keeps_only_items_matching_all_required_tags_case_insensitively(self):
        items = [
            {"id": 1, "tags": ["Coffee", "Travel"]},
            {"id": 2, "tags": ["coffee"]},
            {"id": 3, "tags": ["music"]},
        ]

        result = apply_filters(items, {"tags": "Coffee,travel"})

        self.assertEqual([i["id"] for i in result], [1])


class ApplySortTests(unittest.TestCase):
    def test_same_city_ranked_before_same_neighborhood_and_rest(self):
        items = [
            {"id": "far", "same_city": False, "same_neighborhood": False, "distance_km": 10},
            {"id": "same_city", "same_city": True, "same_neighborhood": False, "distance_km": 50},
            {"id": "same_neighborhood", "same_city": False, "same_neighborhood": True, "distance_km": 5},
        ]

        result = apply_sort(items, {})

        self.assertEqual([i["id"] for i in result], ["same_city", "same_neighborhood", "far"])

    def test_ties_broken_by_shared_tags_then_popularity(self):
        items = [
            {"id": "low", "same_city": True, "same_neighborhood": False, "distance_km": 0,
             "shared_tags_count": 1, "popularity_score": 5},
            {"id": "high", "same_city": True, "same_neighborhood": False, "distance_km": 0,
             "shared_tags_count": 3, "popularity_score": 1},
        ]

        result = apply_sort(items, {})

        self.assertEqual([i["id"] for i in result], ["high", "low"])


class SharedTagCountTests(DBTestCase):
    def test_counts_only_tags_shared_by_both_users(self):
        from app.db import query_all

        alice = self.create_user(email="a@example.com", username="alice")
        bob = self.create_user(email="b@example.com", username="bob")

        for name in ("coffee", "travel", "music"):
            execute("INSERT INTO tags (name) VALUES (?)", (name,))
        tag_ids = {row["name"]: row["id"] for row in query_all("SELECT id, name FROM tags")}

        execute("INSERT INTO user_tags (user_id, tag_id) VALUES (?, ?)", (alice, tag_ids["coffee"]))
        execute("INSERT INTO user_tags (user_id, tag_id) VALUES (?, ?)", (alice, tag_ids["travel"]))
        execute("INSERT INTO user_tags (user_id, tag_id) VALUES (?, ?)", (bob, tag_ids["coffee"]))
        execute("INSERT INTO user_tags (user_id, tag_id) VALUES (?, ?)", (bob, tag_ids["music"]))

        self.assertEqual(shared_tag_count(alice, bob), 1)

    def test_zero_when_no_shared_tags(self):
        alice = self.create_user(email="a@example.com", username="alice")
        bob = self.create_user(email="b@example.com", username="bob")

        self.assertEqual(shared_tag_count(alice, bob), 0)


class CandidateProfilesTests(DBTestCase):
    def _set_gender(self, user_id, gender, sexual_preference="everyone"):
        execute(
            "UPDATE profiles SET gender = ?, sexual_preference = ? WHERE user_id = ?",
            (gender, sexual_preference, user_id),
        )

    def test_excludes_self(self):
        viewer = self.create_user(email="v@example.com", username="viewer")

        self.assertEqual(candidate_profiles(viewer), [])

    def test_excludes_gender_incompatible_candidates(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        self._set_gender(viewer, "female", "men")

        incompatible = self.create_user(email="c1@example.com", username="c1")
        self._set_gender(incompatible, "female", "everyone")

        compatible = self.create_user(email="c2@example.com", username="c2")
        self._set_gender(compatible, "male", "everyone")

        result = candidate_profiles(viewer)

        self.assertEqual([c["id"] for c in result], [compatible])

    def test_excludes_blocked_candidates(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        blocked = self.create_user(email="b@example.com", username="blocked")
        execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (viewer, blocked))

        self.assertEqual(candidate_profiles(viewer), [])

    def test_candidates_never_expose_another_users_email(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        other = self.create_user(email="secret@example.com", username="other")

        result = candidate_profiles(viewer)

        self.assertEqual([c["id"] for c in result], [other])
        self.assertNotIn("email", result[0])

    def test_ranks_same_city_candidates_first(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        execute("UPDATE profiles SET city = 'Paris' WHERE user_id = ?", (viewer,))

        same_city = self.create_user(email="s@example.com", username="samecity")
        execute("UPDATE profiles SET city = 'Paris' WHERE user_id = ?", (same_city,))

        other_city = self.create_user(email="o@example.com", username="othercity")
        execute("UPDATE profiles SET city = 'Lyon' WHERE user_id = ?", (other_city,))

        result = candidate_profiles(viewer)

        self.assertEqual([c["id"] for c in result], [same_city, other_city])


if __name__ == "__main__":
    unittest.main()
