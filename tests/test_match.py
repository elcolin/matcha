import unittest

from app.match.routes import _bucket_rank


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
    """Unit tests for _bucket_rank, the sort key used by candidate_profiles()."""

    def test_same_city_and_neighborhood_ranks_before_same_city_only(self):
        same_place = _candidate(same_city=True, same_neighborhood=True, distance_km=50)
        same_city = _candidate(same_city=True, distance_km=0)

        self.assertLess(_bucket_rank(same_place), _bucket_rank(same_city))

    def test_same_city_ranks_before_nearby_other_city(self):
        same_city = _candidate(same_city=True, distance_km=50)
        nearby = _candidate(distance_km=0)

        self.assertLess(_bucket_rank(same_city), _bucket_rank(nearby))

    def test_closer_distance_bucket_ranks_first_regardless_of_tags(self):
        near = _candidate(distance_km=1)
        far = _candidate(distance_km=100, shared_tags_count=5, popularity_score=100)

        self.assertLess(_bucket_rank(near), _bucket_rank(far))

    def test_within_bucket_sorted_by_shared_tags_descending(self):
        more_tags = _candidate(distance_km=20, shared_tags_count=3)
        fewer_tags = _candidate(distance_km=5, shared_tags_count=1)

        self.assertLess(_bucket_rank(more_tags), _bucket_rank(fewer_tags))

    def test_within_bucket_and_tags_sorted_by_popularity_descending(self):
        more_popular = _candidate(distance_km=20, shared_tags_count=2, popularity_score=10)
        less_popular = _candidate(distance_km=5, shared_tags_count=2, popularity_score=1)

        self.assertLess(_bucket_rank(more_popular), _bucket_rank(less_popular))

    def test_distance_is_the_last_tiebreaker(self):
        near = _candidate(distance_km=5)
        far = _candidate(distance_km=20)

        self.assertLess(_bucket_rank(near), _bucket_rank(far))

    def test_missing_distance_ranks_last(self):
        missing_distance = _candidate(distance_km=None)
        sentinel_distance = _candidate(distance_km=99999)
        antipode = _candidate(distance_km=20015)  # max great-circle distance

        self.assertLess(_bucket_rank(antipode), _bucket_rank(missing_distance))
        self.assertLess(_bucket_rank(antipode), _bucket_rank(sentinel_distance))

    def test_full_ordering_contract(self):
        far = _candidate(distance_km=80)
        near_other_city = _candidate(distance_km=10)
        same_city_low_pop = _candidate(same_city=True, distance_km=5, popularity_score=1)
        same_city_high_pop = _candidate(same_city=True, distance_km=5, popularity_score=9)
        same_place = _candidate(same_city=True, same_neighborhood=True, distance_km=8)

        items = [far, near_other_city, same_city_low_pop, same_city_high_pop, same_place]

        self.assertEqual(
            sorted(items, key=_bucket_rank),
            [same_place, same_city_high_pop, same_city_low_pop, near_other_city, far],
        )


if __name__ == "__main__":
    unittest.main()
