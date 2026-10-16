import unittest
from unittest.mock import MagicMock, call, patch

from geopy.exc import (
    GeocoderRateLimited,
    GeocoderServiceError,
    GeocoderTimedOut,
    GeocoderUnavailable,
    GeopyError,
)

from app.profile import geolocation
from app.utils import APIError

# Every failure mode a Nominatim call can raise (geopy hierarchy + raw
# network/SSL errors, which surface as OSError subclasses).
GEOCODER_FAILURES = [
    GeocoderTimedOut("timed out"),
    GeocoderUnavailable("unavailable"),
    GeocoderServiceError("service error"),
    GeocoderRateLimited("rate limited"),
    GeopyError("generic"),
    OSError("network down"),
]


def _reverse_result(address):
    location = MagicMock()
    location.raw = {"address": address}
    return location


class GeolocatorConfigTests(unittest.TestCase):
    def test_geolocator_has_timeout_and_app_specific_user_agent(self):
        self.assertEqual(geolocation.geolocator.timeout, 10)
        user_agent = geolocation.geolocator.headers.get("User-Agent", "")
        self.assertTrue(user_agent)
        self.assertIn("matcha", user_agent.lower())
        self.assertNotIn("@", user_agent)


class GetLocationFromCoordsTests(unittest.TestCase):
    @patch("app.profile.geolocation.geolocator")
    def test_raises_api_error_when_reverse_geocoding_finds_nothing(self, mock_geolocator):
        mock_geolocator.reverse.return_value = None

        with self.assertRaises(APIError):
            geolocation.get_location_from_coords(48.85, 2.35)

        mock_geolocator.reverse.assert_called_once_with((48.85, 2.35), exactly_one=True)

    @patch("app.profile.geolocation.geolocator")
    def test_every_geocoder_failure_becomes_api_error(self, mock_geolocator):
        for exc in GEOCODER_FAILURES:
            with self.subTest(exc=type(exc).__name__):
                mock_geolocator.reverse.side_effect = exc
                with self.assertRaises(APIError) as ctx:
                    geolocation.get_location_from_coords(48.85, 2.35)
                self.assertTrue(ctx.exception.message)

    @patch("app.profile.geolocation.geolocator")
    def test_extracts_city_and_neighbourhood_from_address(self, mock_geolocator):
        mock_geolocator.reverse.return_value = _reverse_result(
            {"city": "Paris", "neighbourhood": "Le Marais", "country": "France"}
        )

        result = geolocation.get_location_from_coords(48.85, 2.35)

        self.assertEqual(result["city"], "Paris")
        self.assertEqual(result["neighbourhood"], "Le Marais")
        self.assertEqual(result["country"], "France")

    @patch("app.profile.geolocation.geolocator")
    def test_city_falls_back_through_smaller_place_types(self, mock_geolocator):
        for key in ("town", "village", "municipality", "hamlet", "city_district"):
            with self.subTest(key=key):
                mock_geolocator.reverse.return_value = _reverse_result({key: f"Some {key}"})
                result = geolocation.get_location_from_coords(48.85, 2.35)
                self.assertEqual(result["city"], f"Some {key}")

    @patch("app.profile.geolocation.geolocator")
    def test_falls_back_to_suburb_for_neighbourhood(self, mock_geolocator):
        mock_geolocator.reverse.return_value = _reverse_result(
            {"city": "Paris", "suburb": "Some Suburb"}
        )

        result = geolocation.get_location_from_coords(48.85, 2.35)

        self.assertEqual(result["neighbourhood"], "Some Suburb")

    @patch("app.profile.geolocation.geolocator")
    def test_raises_api_error_when_no_city_like_key(self, mock_geolocator):
        mock_geolocator.reverse.return_value = _reverse_result(
            {"country": "France", "suburb": "Somewhere"}
        )

        with self.assertRaises(APIError):
            geolocation.get_location_from_coords(48.85, 2.35)

    @patch("app.profile.geolocation.geolocator")
    def test_raises_api_error_when_address_is_missing(self, mock_geolocator):
        mock_geolocator.reverse.return_value = _reverse_result(None)

        with self.assertRaises(APIError):
            geolocation.get_location_from_coords(48.85, 2.35)


class GeocodeCityTests(unittest.TestCase):
    @patch("app.profile.geolocation.geolocator")
    def test_returns_lat_lon_for_a_known_city(self, mock_geolocator):
        mock_geolocator.geocode.return_value = MagicMock(latitude=45.764, longitude=4.8357)

        result = geolocation.geocode_city("Lyon")

        self.assertEqual(result, (45.764, 4.8357))
        mock_geolocator.geocode.assert_called_once_with("Lyon", exactly_one=True)

    @patch("app.profile.geolocation.geolocator")
    def test_includes_neighborhood_in_query_when_given(self, mock_geolocator):
        mock_geolocator.geocode.return_value = MagicMock(latitude=48.86, longitude=2.36)

        geolocation.geocode_city("Paris", "Le Marais")

        mock_geolocator.geocode.assert_called_once_with("Le Marais, Paris", exactly_one=True)

    @patch("app.profile.geolocation.geolocator")
    def test_raises_api_error_for_an_unrecognized_city(self, mock_geolocator):
        mock_geolocator.geocode.return_value = None

        with self.assertRaises(APIError):
            geolocation.geocode_city("Not A Real Place")

    @patch("app.profile.geolocation.geolocator")
    def test_every_geocoder_failure_becomes_api_error(self, mock_geolocator):
        for exc in GEOCODER_FAILURES:
            with self.subTest(exc=type(exc).__name__):
                mock_geolocator.geocode.side_effect = exc
                with self.assertRaises(APIError) as ctx:
                    geolocation.geocode_city("Paris")
                self.assertTrue(ctx.exception.message)

    @patch("app.profile.geolocation.geolocator")
    def test_unknown_neighborhood_falls_back_to_city_alone(self, mock_geolocator):
        mock_geolocator.geocode.side_effect = [
            None,
            MagicMock(latitude=48.8566, longitude=2.3522),
        ]

        result = geolocation.geocode_city("Paris", "Nowhereville")

        self.assertEqual(result, (48.8566, 2.3522))
        self.assertEqual(
            mock_geolocator.geocode.call_args_list,
            [
                call("Nowhereville, Paris", exactly_one=True),
                call("Paris", exactly_one=True),
            ],
        )

    @patch("app.profile.geolocation.geolocator")
    def test_unknown_neighborhood_and_city_raises_api_error(self, mock_geolocator):
        mock_geolocator.geocode.return_value = None

        with self.assertRaises(APIError) as ctx:
            geolocation.geocode_city("Atlantis", "Nowhereville")

        self.assertEqual(mock_geolocator.geocode.call_count, 2)
        self.assertEqual(ctx.exception.message, "'Atlantis' is not a recognized location.")

    @patch("app.profile.geolocation.geolocator")
    def test_service_error_is_not_retried_with_city_alone(self, mock_geolocator):
        for exc in (GeocoderUnavailable("unavailable"), OSError("network down")):
            with self.subTest(exc=type(exc).__name__):
                mock_geolocator.reset_mock()
                mock_geolocator.geocode.side_effect = exc
                with self.assertRaises(APIError) as ctx:
                    geolocation.geocode_city("Paris", "Le Marais")
                self.assertEqual(ctx.exception.status, 503)
                mock_geolocator.geocode.assert_called_once_with(
                    "Le Marais, Paris", exactly_one=True
                )

    @patch("app.profile.geolocation.geolocator")
    def test_unknown_city_without_neighborhood_is_queried_once(self, mock_geolocator):
        mock_geolocator.geocode.return_value = None

        with self.assertRaises(APIError):
            geolocation.geocode_city("Atlantis")

        mock_geolocator.geocode.assert_called_once_with("Atlantis", exactly_one=True)


if __name__ == "__main__":
    unittest.main()
