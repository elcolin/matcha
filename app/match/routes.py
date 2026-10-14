from flask import Blueprint, g, jsonify, request

from app.db import query_all
from app.profile.routes import _build_profile_payload, _profile_payload
from app.utils import login_required

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
    viewer = _profile_payload(viewer_id)
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
