import unittest

from app.match.routes import _bucket_rank, apply_sort


def _candidate(**overrides):
    base = {
        "same_city": False,
        "same_neighborhood": False,
        "distance_km": 10,
        "shared_tags_count": 0,
        "popularity_score": 0,
    }
    base.update(overrides)
    return base


class BucketRankTests(unittest.TestCase):
    """Unit tests for the shared _bucket_rank helper used by suggestion sorting."""

    def test_same_city_ranks_before_same_neighborhood(self):
        same_city = _candidate(same_city=True, distance_km=50)
        same_neighborhood = _candidate(same_neighborhood=True, distance_km=0)

        self.assertLess(_bucket_rank(same_city), _bucket_rank(same_neighborhood))

    def test_same_neighborhood_ranks_before_rest(self):
        same_neighborhood = _candidate(same_neighborhood=True, distance_km=50)
        rest = _candidate(distance_km=0)

        self.assertLess(_bucket_rank(same_neighborhood), _bucket_rank(rest))

    def test_within_bucket_sorted_by_distance_ascending(self):
        near = _candidate(distance_km=1)
        far = _candidate(distance_km=100)

        self.assertLess(_bucket_rank(near), _bucket_rank(far))

    def test_within_same_distance_sorted_by_shared_tags_descending(self):
        more_tags = _candidate(distance_km=5, shared_tags_count=3)
        fewer_tags = _candidate(distance_km=5, shared_tags_count=1)

        self.assertLess(_bucket_rank(more_tags), _bucket_rank(fewer_tags))

    def test_within_same_distance_and_tags_sorted_by_popularity_descending(self):
        more_popular = _candidate(distance_km=5, shared_tags_count=2, popularity_score=10)
        less_popular = _candidate(distance_km=5, shared_tags_count=2, popularity_score=1)

        self.assertLess(_bucket_rank(more_popular), _bucket_rank(less_popular))

    def test_missing_distance_is_treated_as_maximal_distance(self):
        missing_distance = _candidate(distance_km=None)
        known_distance = _candidate(distance_km=99998)

        self.assertLess(_bucket_rank(known_distance), _bucket_rank(missing_distance))


class ApplySortTests(unittest.TestCase):
    """Integration-style test for apply_sort, exercising the full ordering contract."""

    def test_apply_sort_orders_by_city_then_neighborhood_then_distance_tags_popularity(self):
        rest_far = _candidate(distance_km=80, shared_tags_count=0, popularity_score=0)
        same_neighborhood = _candidate(same_neighborhood=True, distance_km=10)
        same_city_low_pop = _candidate(same_city=True, distance_km=5, popularity_score=1)
        same_city_high_pop = _candidate(same_city=True, distance_km=5, popularity_score=9)

        items = [rest_far, same_neighborhood, same_city_low_pop, same_city_high_pop]
        sorted_items = apply_sort(items, args={})

        self.assertEqual(
            sorted_items,
            [same_city_high_pop, same_city_low_pop, same_neighborhood, rest_far],
        )


if __name__ == "__main__":
    unittest.main()
