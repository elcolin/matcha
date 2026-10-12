import unittest
from unittest.mock import MagicMock, patch

from app.profile import geolocation
from app.utils import APIError


class GetLocationFromCoordsTests(unittest.TestCase):
    @patch("app.profile.geolocation.geolocator")
    def test_returns_none_when_reverse_geocoding_finds_nothing(self, mock_geolocator):
        mock_geolocator.reverse.return_value = None

        result = geolocation.get_location_from_coords(48.85, 2.35)

        self.assertIsNone(result)
        mock_geolocator.reverse.assert_called_once_with((48.85, 2.35), exactly_one=True)

    @patch("app.profile.geolocation.geolocator")
    def test_extracts_city_and_neighbourhood_from_address(self, mock_geolocator):
        location = MagicMock()
        location.raw = {
            "address": {
                "city": "Paris",
                "neighbourhood": "Le Marais",
                "country": "France",
            }
        }
        mock_geolocator.reverse.return_value = location

        result = geolocation.get_location_from_coords(48.85, 2.35)

        self.assertEqual(result["city"], "Paris")
        self.assertEqual(result["neighbourhood"], "Le Marais")
        self.assertEqual(result["country"], "France")

    @patch("app.profile.geolocation.geolocator")
    def test_falls_back_to_town_then_village_when_city_missing(self, mock_geolocator):
        location = MagicMock()
        location.raw = {"address": {"town": "Some Town"}}
        mock_geolocator.reverse.return_value = location

        result = geolocation.get_location_from_coords(48.85, 2.35)
        self.assertEqual(result["city"], "Some Town")

        location.raw = {"address": {"village": "Some Village"}}
        result = geolocation.get_location_from_coords(48.85, 2.35)
        self.assertEqual(result["city"], "Some Village")

    @patch("app.profile.geolocation.geolocator")
    def test_falls_back_to_suburb_for_neighbourhood(self, mock_geolocator):
        location = MagicMock()
        location.raw = {"address": {"suburb": "Some Suburb"}}
        mock_geolocator.reverse.return_value = location

        result = geolocation.get_location_from_coords(48.85, 2.35)

        self.assertEqual(result["neighbourhood"], "Some Suburb")

    @patch("app.profile.geolocation.geolocator")
    def test_raises_api_error_when_address_is_missing(self, mock_geolocator):
        location = MagicMock()
        location.raw = {"address": None}
        mock_geolocator.reverse.return_value = location

        with self.assertRaises(APIError):
            geolocation.get_location_from_coords(48.85, 2.35)


class CheckIfCityValidTests(unittest.TestCase):
    @patch("app.profile.geolocation.geolocator")
    def test_does_not_raise_for_a_known_city(self, mock_geolocator):
        mock_geolocator.geocode.return_value = MagicMock()

        geolocation.check_if_city_valid("Paris")

        mock_geolocator.geocode.assert_called_once_with("Paris", exactly_one=True)

    @patch("app.profile.geolocation.geolocator")
    def test_raises_api_error_for_an_unrecognized_city(self, mock_geolocator):
        mock_geolocator.geocode.return_value = None

        with self.assertRaises(APIError):
            geolocation.check_if_city_valid("Not A Real Place")


if __name__ == "__main__":
    unittest.main()
