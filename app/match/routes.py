import math

from flask import Blueprint, g, jsonify, request

from app.db import query_all
from app.profile.routes import _profile_payload
from app.utils import is_blocked_between, login_required

match_bp = Blueprint("match", __name__, url_prefix="/match")
MISSING_DISTANCE_KM = 99999

EARTH_RADIUS_KM = 6371.0


def calculate_distance(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in km; sentinel if any coord is missing."""
    if None in (lat1, lon1, lat2, lon2):
        return float(MISSING_DISTANCE_KM)
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def is_gender_compatible(current_pref, candidate_gender):
    if current_pref == "everyone":
        return True
    if current_pref == "men":
        return candidate_gender == "male"
    if current_pref == "women":
        return candidate_gender == "female"
    return True


def shared_tag_count(current_id, candidate_id):
    rows = query_all(
        """
        SELECT COUNT(*) AS c
        FROM user_tags a
        JOIN user_tags b ON a.tag_id = b.tag_id
        WHERE a.user_id = ? AND b.user_id = ?
        """,
        (current_id, candidate_id),
    )
    return rows[0]["c"] if rows else 0


def _bucket_rank(item):
    distance = item.get("distance_km") if item.get("distance_km") is not None else MISSING_DISTANCE_KM
    if item.get("same_city"):
        return (0, 0, distance, -item.get("shared_tags_count", 0), -item.get("popularity_score", 0))
    if item.get("same_neighborhood"):
        return (1, 0, distance, -item.get("shared_tags_count", 0), -item.get("popularity_score", 0))
    return (2, distance, -item.get("shared_tags_count", 0), -item.get("popularity_score", 0))


def candidate_profiles(viewer_id: int):
    viewer = _profile_payload(viewer_id, include_coordinates=True)
    if not viewer:
        return []

    candidates = []
    for row in query_all("SELECT id FROM users WHERE id != ?", (viewer_id,)):
        candidate = _profile_payload(row["id"], include_coordinates=True)
        if not candidate:
            continue
        if is_blocked_between(viewer_id, candidate["id"]):
            continue
        if not is_gender_compatible(viewer.get("sexual_preference"), candidate.get("gender")):
            continue
        if not is_gender_compatible(candidate.get("sexual_preference"), viewer.get("gender")):
            continue

        shared_tags = shared_tag_count(viewer_id, candidate["id"])
        distance_km = calculate_distance(
            viewer.get("latitude"),
            viewer.get("longitude"),
            candidate.get("latitude"),
            candidate.get("longitude"),
        )
        same_city = bool(
            viewer.get("city") and candidate.get("city") and
            viewer.get("city").strip().lower() == candidate.get("city").strip().lower()
        )
        same_neighborhood = bool(
            viewer.get("neighborhood") and candidate.get("neighborhood") and
            viewer.get("neighborhood").strip().lower() == candidate.get("neighborhood").strip().lower()
        )
        candidate["shared_tags_count"] = shared_tags
        candidate["distance_km"] = distance_km
        candidate["same_city"] = same_city
        candidate["same_neighborhood"] = same_neighborhood
        # Coordinates were only needed for the distance: never expose them.
        candidate.pop("latitude")
        candidate.pop("longitude")
        candidates.append(candidate)

    candidates.sort(key=_bucket_rank)

    return candidates

def apply_filters(items, args):
    required_tags = {t.strip().lower() for t in args.get("tags", "").split(",") if t.strip()}

    def ok(item):
        if required_tags and not required_tags.issubset(set(t.lower() for t in item.get("tags", []))):
            return False
        return True

    return [item for item in items if ok(item)]

def apply_sort(items, args):
    items.sort(key=_bucket_rank)
    return items

@match_bp.route("", methods=["GET"])
@login_required
def suggestions():
    items = candidate_profiles(g.current_user["id"])
    items = apply_filters(items, request.args)
    items = apply_sort(items, request.args) 
    return jsonify(items)
