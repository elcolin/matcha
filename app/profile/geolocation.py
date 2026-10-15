from geopy.exc import GeopyError
from geopy.geocoders import Nominatim
import certifi
import os
from app.utils import APIError

os.environ["SSL_CERT_FILE"] = certifi.where()

# Nominatim usage policy: an app-specific User-Agent is required (no personal
# contact data here). timeout bounds every request so a slow service can never
# hang a profile save.
GEOCODER_USER_AGENT = "matcha-42-dating-app/1.0"
GEOCODER_TIMEOUT_SECONDS = 10

geolocator = Nominatim(user_agent=GEOCODER_USER_AGENT, timeout=GEOCODER_TIMEOUT_SECONDS)

# Ordered from most to least specific "city-like" Nominatim address keys.
CITY_KEYS = ("city", "town", "village", "municipality", "hamlet", "city_district")

SERVICE_UNAVAILABLE_MESSAGE = (
    "The location service is unavailable right now. Please try again later."
)


def _call_geocoder(method, *args, **kwargs):
    """Run a geolocator call, turning every geopy/network failure into APIError."""
    try:
        return method(*args, **kwargs)
    except (GeopyError, OSError):
        raise APIError(SERVICE_UNAVAILABLE_MESSAGE, 503)


def get_location_from_coords(lat, lon):
    location = _call_geocoder(geolocator.reverse, (lat, lon), exactly_one=True)
    if location is None:
        raise APIError("GPS localisation failed, please enter your city manually.")

    address = location.raw.get("address") or {}
    city = next((address[key] for key in CITY_KEYS if address.get(key)), None)
    if not city:
        raise APIError("No city found for your GPS position, please enter your city manually.")
    return {
        "city": city,
        "neighbourhood": address.get("neighbourhood") or address.get("suburb"),
        "country": address.get("country"),
        "raw": address,  # useful for debugging what fields are actually available
    }


def geocode_city(city, neighborhood=None):
    """Forward-geocode a city (optionally narrowed by neighborhood) to (lat, lon)."""
    query = f"{neighborhood}, {city}" if neighborhood else city
    location = _call_geocoder(geolocator.geocode, query, exactly_one=True)
    if location is None:
        raise APIError(f"'{query}' is not a recognized location.")
    return (location.latitude, location.longitude)
