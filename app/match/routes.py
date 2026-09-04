from flask import Blueprint, g, jsonify, request

from app.db import query_all
from app.profile.routes import _profile_payload
from app.utils import is_blocked_between, login_required

match_bp = Blueprint("match", __name__, url_prefix="/match")
MISSING_DISTANCE_KM = 99999

def calculate_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 99999.0
    lat_diff = abs(float(lat1) - float(lat2)) * 111.0
    lon_diff = abs(float(lon1) - float(lon2)) * 111.0
    return lat_diff + lon_diff


def is_gender_compatible(current_pref, candidate_gender):
    if current_pref == "everyone":
        return True
    if current_pref == "men":
        return candidate_gender == "men"
    if current_pref == "women":
        return candidate_gender == "women"
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

def candidate_profiles(viewer_id: int):
    viewer = _profile_payload(viewer_id)
    if not viewer:
        return []

    candidates = []
    for row in query_all("SELECT id FROM users WHERE id != ?", (viewer_id,)):
        candidate = _profile_payload(row["id"])
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
        candidate["shared_tags_count"] = shared_tags
        candidate["distance_km"] = distance_km
        candidate["same_city"] = same_city
        candidates.append(candidate)

    candidates.sort(
        key=lambda c: (
            0 if c.get("same_city") else 1,
            c.get("distance_km") if c.get("distance_km") is not None else MISSING_DISTANCE_KM,
            -c.get("shared_tags_count", 0),
            -c.get("popularity_score", 0),
        )
    )
    return candidates

def apply_filters(items, args):
    required_tags = {t.strip().lower() for t in args.get("tags", "").split(",") if t.strip()}

    def ok(item):
        if required_tags and not required_tags.issubset(set(t.lower() for t in item.get("tags", []))):
            return False
        return True

    return [item for item in items if ok(item)]

def apply_sort(items, args):
    items.sort(
        key=lambda item: (
            0 if item.get("same_city") else 1,
            item.get("distance_km") if item.get("distance_km") is not None else MISSING_DISTANCE_KM,
            -item.get("shared_tags_count", 0),
            -item.get("popularity_score", 0),
        )
    )
    return items

@match_bp.route("", methods=["GET"])
@login_required
def suggestions():
    items = candidate_profiles(g.current_user["id"])
    items = apply_filters(items, request.args)
    items = apply_sort(items, request.args)
    return jsonify(items)
