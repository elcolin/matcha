import math

from flask import Blueprint, g, jsonify, request

from app.db import query_all
from app.profile.routes import _build_profile_payload, _profile_payload
from app.utils import login_required

match_bp = Blueprint("match", __name__, url_prefix="/match")
MISSING_DISTANCE_KM = 99999
LOCATION_BUCKET_KM = 25


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

def _location_tier(item):
    if item.get("same_city") and item.get("same_neighborhood"):
        return 0
    if item.get("same_city"):
        return 1
    distance = item.get("distance_km")
    if distance is None or distance >= MISSING_DISTANCE_KM:
        return 999  # unknown location goes last
    return 2 + int(distance // LOCATION_BUCKET_KM) 


def _bucket_rank(item):
    return (
        _location_tier(item),
        -item.get("shared_tags_count", 0),
        -item.get("popularity_score", 0),
        item.get("distance_km", MISSING_DISTANCE_KM),  # last tiebreaker only
    )


def _same_place(a, b):
    return bool(a and b and a.strip().lower() == b.strip().lower())


def _load_candidate_data(viewer_id: int):
    """Load every non-blocked candidate with their tags, photos and shared-tag
    counts in a constant number of queries (no per-candidate query)."""
    rows = query_all(
        """
        SELECT u.id, u.username, u.first_name, u.last_name, u.last_seen_at, u.online_until,
               p.gender, p.sexual_preference, p.bio, p.city, p.neighborhood,
               p.latitude, p.longitude, p.location_consent_gps, p.popularity_score, p.age
        FROM users u
        JOIN profiles p ON p.user_id = u.id
        WHERE u.id != ?
          AND NOT EXISTS (
              SELECT 1 FROM blocks b
              WHERE (b.blocker_id = ? AND b.blocked_id = u.id)
                 OR (b.blocker_id = u.id AND b.blocked_id = ?)
          )
        ORDER BY u.id
        """,
        (viewer_id, viewer_id, viewer_id),
    )

    tags_by_user = {}
    for r in query_all(
        """
        SELECT ut.user_id, t.name
        FROM user_tags ut
        JOIN tags t ON t.id = ut.tag_id
        ORDER BY ut.user_id, t.name ASC
        """
    ):
        tags_by_user.setdefault(r["user_id"], []).append(r["name"])

    photos_by_user = {}
    for r in query_all(
        """
        SELECT id, user_id, url, is_profile_photo
        FROM photos
        ORDER BY user_id, is_profile_photo DESC, id ASC
        """
    ):
        photos_by_user.setdefault(r["user_id"], []).append(
            {"id": r["id"], "url": r["url"], "is_profile_photo": r["is_profile_photo"]}
        )

    shared_by_user = {
        r["user_id"]: r["c"]
        for r in query_all(
            """
            SELECT ut.user_id, COUNT(*) AS c
            FROM user_tags ut
            JOIN user_tags vt ON vt.tag_id = ut.tag_id AND vt.user_id = ?
            WHERE ut.user_id != ?
            GROUP BY ut.user_id
            """,
            (viewer_id, viewer_id),
        )
    }
    return rows, tags_by_user, photos_by_user, shared_by_user


def candidate_profiles(viewer_id: int):
    viewer = _profile_payload(viewer_id, include_coordinates=True)
    if not viewer:
        return []

    rows, tags_by_user, photos_by_user, shared_by_user = _load_candidate_data(viewer_id)

    candidates = []
    for row in rows:
        # Filtering and ranking signals (computed before shaping the output).
        sexual_preference = row["sexual_preference"] or "everyone"
        if not is_gender_compatible(viewer["sexual_preference"], row["gender"]):
            continue
        if not is_gender_compatible(sexual_preference, viewer["gender"]):
            continue
        extra = {
            "shared_tags_count": shared_by_user.get(row["id"], 0),
            "distance_km": calculate_distance(
                viewer["latitude"], viewer["longitude"], row["latitude"], row["longitude"]
            ),
            "same_city": _same_place(viewer["city"], row["city"]),
            "same_neighborhood": _same_place(viewer["neighborhood"], row["neighborhood"]),
        }

        # Output shaping.
        candidate = _build_profile_payload(
            row, tags_by_user.get(row["id"], []), photos_by_user.get(row["id"], [])
        )
        candidate.update(extra)
        candidates.append(candidate)

    candidates.sort(key=_bucket_rank)

    return candidates


@match_bp.route("", methods=["GET"])
@login_required
def suggestions():
    items = candidate_profiles(g.current_user["id"])

    return jsonify(items)
