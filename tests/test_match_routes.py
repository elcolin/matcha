import unittest
from datetime import datetime, timedelta, timezone

from app.db import execute, get_db
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

    def test_computes_great_circle_distance_in_km(self):
        # Paris -> Lyon is ~392 km as the crow flies (haversine, R = 6371 km).
        paris, lyon = (48.8566, 2.3522), (45.7640, 4.8357)

        distance = calculate_distance(*paris, *lyon)

        self.assertAlmostEqual(distance, 392, delta=5)
        self.assertAlmostEqual(calculate_distance(*lyon, *paris), distance)

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

    def test_candidates_include_online_status(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        online_candidate = self.create_user(email="on@example.com", username="online_user")
        offline_candidate = self.create_user(email="off@example.com", username="offline_user")

        future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        execute("UPDATE users SET online_until = ? WHERE id = ?", (future, online_candidate))

        result = candidate_profiles(viewer)
        by_id = {c["id"]: c for c in result}

        self.assertTrue(by_id[online_candidate]["online"])
        self.assertFalse(by_id[offline_candidate]["online"])


class CandidateProfilesCharacterizationTests(DBTestCase):
    """Pins the exact output (shape, values, order) of candidate_profiles()."""

    def _profile(self, user_id, *, gender, sexual_preference="everyone", bio="", city=None,
                 neighborhood=None, latitude=None, longitude=None, location_consent_gps=0,
                 popularity_score=0, age=None):
        execute(
            """
            UPDATE profiles
            SET gender = ?, sexual_preference = ?, bio = ?, city = ?, neighborhood = ?,
                latitude = ?, longitude = ?, location_consent_gps = ?, popularity_score = ?, age = ?
            WHERE user_id = ?
            """,
            (gender, sexual_preference, bio, city, neighborhood, latitude, longitude,
             location_consent_gps, popularity_score, age, user_id),
        )

    def _tag(self, user_id, name):
        execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        execute(
            "INSERT INTO user_tags (user_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
            (user_id, name),
        )

    def _photo(self, user_id, url, is_profile_photo):
        return execute(
            "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, ?, ?)",
            (user_id, url, is_profile_photo),
        ).lastrowid

    def test_full_output_and_order(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        self._profile(viewer, gender="female", sexual_preference="men", city="Paris",
                      neighborhood="Marais", latitude=48.0, longitude=2.0)
        self._tag(viewer, "coffee")
        self._tag(viewer, "travel")

        blocked_by_viewer = self.create_user(email="b1@example.com", username="b1")
        self._profile(blocked_by_viewer, gender="male")
        execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (viewer, blocked_by_viewer))

        blocking_viewer = self.create_user(email="b2@example.com", username="b2")
        self._profile(blocking_viewer, gender="male")
        execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (blocking_viewer, viewer))

        wants_men = self.create_user(email="g1@example.com", username="g1")
        self._profile(wants_men, gender="male", sexual_preference="men")

        not_a_man = self.create_user(email="g2@example.com", username="g2")
        self._profile(not_a_man, gender="female")

        far = self.create_user(email="far@example.com", username="far")
        self._profile(far, gender="male")

        same_city = self.create_user(email="sc@example.com", username="samecity",
                                     first_name="Sam", last_name="City")
        self._profile(same_city, gender="male", sexual_preference=None, bio=None,
                      city="  paris ", age=25)
        self._tag(same_city, "zebra")
        self._tag(same_city, "coffee")
        self._tag(same_city, "art")
        later_photo = self._photo(same_city, "b.jpg", 0)
        profile_photo = self._photo(same_city, "a.jpg", 1)

        same_hood = self.create_user(email="sn@example.com", username="samehood")
        self._profile(same_hood, gender="male", sexual_preference="women", city="Lyon",
                      neighborhood=" marais", latitude=49.0, longitude=3.0,
                      location_consent_gps=1, popularity_score=42, age=30, bio="hello")
        self._tag(same_hood, "travel")
        self._tag(same_hood, "coffee")
        future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        execute("UPDATE users SET online_until = ?, last_seen_at = ? WHERE id = ?",
                (future, "2026-01-01T00:00:00+00:00", same_hood))

        result = candidate_profiles(viewer)

        base = {
            "first_name": "First", "last_name": "Last", "sexual_preference": "everyone",
            "bio": "", "city": None, "neighborhood": None,
            "location_consent_gps": False, "popularity_score": 0,
            "age": None, "online": False, "last_seen_at": None, "tags": [], "photos": [],
            "shared_tags_count": 0, "distance_km": 99999.0, "same_city": False,
            "same_neighborhood": False,
        }
        expected = [
            {**base, "id": same_city, "username": "samecity", "first_name": "Sam",
             "last_name": "City", "gender": "male", "city": "  paris ", "age": 25,
             "tags": ["art", "coffee", "zebra"],
             "photos": [
                 {"id": profile_photo, "url": "a.jpg", "is_profile_photo": 1},
                 {"id": later_photo, "url": "b.jpg", "is_profile_photo": 0},
             ],
             "shared_tags_count": 1, "same_city": True},
            {**base, "id": same_hood, "username": "samehood", "gender": "male",
             "sexual_preference": "women", "bio": "hello", "city": "Lyon",
             "neighborhood": " marais",
             "location_consent_gps": True, "popularity_score": 42, "age": 30,
             "online": True, "last_seen_at": "2026-01-01T00:00:00+00:00",
             "tags": ["coffee", "travel"], "shared_tags_count": 2,
             "distance_km": calculate_distance(48.0, 2.0, 49.0, 3.0),
             "same_neighborhood": True},
            {**base, "id": far, "username": "far", "gender": "male"},
        ]
        self.assertEqual(result, expected)

    def test_ties_keep_user_id_order(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        ids = [self.create_user(email=f"c{i}@example.com", username=f"c{i}") for i in range(4)]

        self.assertEqual([c["id"] for c in candidate_profiles(viewer)], ids)

    def test_excludes_candidate_without_profile_row(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        orphan = self.create_user(email="o@example.com", username="orphan")
        execute("DELETE FROM profiles WHERE user_id = ?", (orphan,))
        kept = self.create_user(email="k@example.com", username="kept")

        self.assertEqual([c["id"] for c in candidate_profiles(viewer)], [kept])

    def test_excludes_candidate_who_blocked_viewer(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        blocker = self.create_user(email="b@example.com", username="blocker")
        execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (blocker, viewer))

        self.assertEqual(candidate_profiles(viewer), [])

    def test_unknown_viewer_returns_empty_list(self):
        self.create_user(email="c@example.com", username="c")

        self.assertEqual(candidate_profiles(9999), [])

    def test_viewer_without_profile_row_returns_empty_list(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        execute("DELETE FROM profiles WHERE user_id = ?", (viewer,))
        self.create_user(email="c@example.com", username="c")

        self.assertEqual(candidate_profiles(viewer), [])


class CandidateProfilesQueryCountTests(DBTestCase):
    """candidate_profiles() must run a constant number of SQL statements (issue #46)."""

    def _count_queries(self, viewer_id):
        statements = []
        db = get_db()
        db.set_trace_callback(statements.append)
        try:
            candidate_profiles(viewer_id)
        finally:
            db.set_trace_callback(None)
        return len(statements)

    def _add_candidates(self, start, count):
        for i in range(start, start + count):
            user_id = self.create_user(email=f"c{i}@example.com", username=f"c{i}")
            execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (f"tag{i % 3}",))
            execute(
                "INSERT INTO user_tags (user_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
                (user_id, f"tag{i % 3}"),
            )
            execute(
                "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, 'p.jpg', 1)",
                (user_id,),
            )

    def test_query_count_does_not_grow_with_candidates(self):
        viewer = self.create_user(email="v@example.com", username="viewer")
        self._add_candidates(0, 5)
        small = self._count_queries(viewer)
        self._add_candidates(5, 10)
        large = self._count_queries(viewer)

        self.assertEqual(small, large)
        self.assertLessEqual(large, 8)

    def test_query_count_bounded_with_no_candidates(self):
        viewer = self.create_user(email="v@example.com", username="viewer")

        self.assertLessEqual(self._count_queries(viewer), 8)


if __name__ == "__main__":
    unittest.main()
