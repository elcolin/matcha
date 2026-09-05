from geopy.geocoders import Nominatim
import certifi
import os
from app.utils import (
    APIError)

os.environ["SSL_CERT_FILE"] = certifi.where()

geolocator = Nominatim(user_agent="matcha-app")  # required: unique app identifier

def get_location_from_coords(lat, lon):
    location = geolocator.reverse((lat, lon), exactly_one=True)
    if location is None:
        return None

    address = location.raw.get("address", {})
    return {
        "city": address.get("city") or address.get("town") or address.get("village"),
        "neighbourhood": address.get("neighbourhood") or address.get("suburb"),
        "country": address.get("country"),
        "raw": address,  # useful for debugging what fields are actually available
    }

def check_if_city_valid(city_name):
    location = geolocator.geocode(city_name, exactly_one=True)
    if (location is None):
        raise APIError(f"'{city_name}' is not a recognized city.")
