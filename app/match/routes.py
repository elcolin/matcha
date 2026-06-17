import math

from flask import Blueprint, g, jsonify, request

from app.db import query_all
from app.profile.routes import _profile_payload
from app.utils import is_blocked_between, login_required

match_bp = Blueprint("match", __name__, url_prefix="/match")


def _distance_km(a_lat, a_lon, b_lat, b_lon):
    if None in (a_lat, a_lon, b_lat, b_lon):
        return None

    r = 6371.0
    lat1 = math.radians(float(a_lat))
    lon1 = math.radians(float(a_lon))
    lat2 = math.radians(float(b_lat))
    lon2 = math.radians(float(b_lon))

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return r * (2 * math.atan2(math.sqrt(x), math.sqrt(1 - x)))


def _is_gender_compatible(viewer_gender, viewer_pref, target_gender):
    viewer_pref = viewer_pref or "bisexual"
    if viewer_pref == "bisexual":
        return True
    if viewer_pref == "straight":
        return viewer_gender and target_gender and viewer_gender != target_gender
    if viewer_pref == "gay":
        return viewer_gender and target_gender and viewer_gender == target_gender
    return True


def _shared_tag_count(viewer_id: int, target_id: int):
    rows = query_all(
        """
        SELECT COUNT(*) AS c
        FROM user_tags a
        JOIN user_tags b ON a.tag_id = b.tag_id
        WHERE a.user_id = ? AND b.user_id = ?
        """,
        (viewer_id, target_id),
    )
    return rows[0]["c"] if rows else 0


def _candidate_profiles(viewer_id: int):
    viewer = _profile_payload(viewer_id)
    rows = query_all("SELECT id FROM users WHERE id != ?", (viewer_id,))

    output = []
    for row in rows:
        candidate = _profile_payload(row["id"])
        if not candidate:
            continue

        if is_blocked_between(viewer_id, candidate["id"]):
            continue

        if not _is_gender_compatible(viewer.get("gender"), viewer.get("sexual_preference"), candidate.get("gender")):
            continue

        if not _is_gender_compatible(candidate.get("gender"), candidate.get("sexual_preference"), viewer.get("gender")):
            continue

        shared_tags = _shared_tag_count(viewer_id, candidate["id"])
        distance_km = _distance_km(viewer.get("latitude"), viewer.get("longitude"), candidate.get("latitude"), candidate.get("longitude"))
        same_area = int(
            (viewer.get("city") and viewer.get("city") == candidate.get("city")) or
            (viewer.get("neighborhood") and viewer.get("neighborhood") == candidate.get("neighborhood"))
        )

        candidate["shared_tags_count"] = shared_tags
        candidate["distance_km"] = distance_km
        candidate["same_area"] = bool(same_area)

        output.append(candidate)

    output.sort(
        key=lambda c: (
            0 if c["same_area"] else 1,
            c["distance_km"] if c["distance_km"] is not None else 99999,
            -c["shared_tags_count"],
            -c.get("popularity_score", 0),
        )
    )
    return output


def _apply_filters(items, args):
    min_age = args.get("min_age", type=int)
    max_age = args.get("max_age", type=int)
    city = args.get("city")
    min_popularity = args.get("min_popularity", type=int)
    max_popularity = args.get("max_popularity", type=int)
    required_tags = {t.strip().lower() for t in args.get("tags", "").split(",") if t.strip()}

    def ok(item):
        age = item.get("age")
        if min_age is not None and (age is None or age < min_age):
            return False
        if max_age is not None and (age is None or age > max_age):
            return False
        if city and (item.get("city") or "").lower() != city.lower():
            return False
        if min_popularity is not None and item.get("popularity_score", 0) < min_popularity:
            return False
        if max_popularity is not None and item.get("popularity_score", 0) > max_popularity:
            return False
        if required_tags and not required_tags.issubset(set(t.lower() for t in item.get("tags", []))):
            return False
        return True

    return [i for i in items if ok(i)]


def _apply_sort(items, args):
    sort_by = args.get("sort_by", "smart")
    order = args.get("order", "desc").lower()
    reverse = order == "desc"

    if sort_by == "age":
        items.sort(key=lambda x: x.get("age") if x.get("age") is not None else -1, reverse=reverse)
    elif sort_by == "location":
        items.sort(key=lambda x: x.get("distance_km") if x.get("distance_km") is not None else 99999, reverse=(not reverse))
    elif sort_by == "popularity":
        items.sort(key=lambda x: x.get("popularity_score", 0), reverse=reverse)
    elif sort_by == "tags":
        items.sort(key=lambda x: x.get("shared_tags_count", 0), reverse=reverse)

    return items


@match_bp.route("", methods=["GET"])
@login_required
def suggestions():
    items = _candidate_profiles(g.current_user["id"])
    items = _apply_filters(items, request.args)
    items = _apply_sort(items, request.args)
    return jsonify(items)


@match_bp.route("/search", methods=["GET"])
@login_required
def advanced_search():
    items = _candidate_profiles(g.current_user["id"])
    items = _apply_filters(items, request.args)
    items = _apply_sort(items, request.args)
    return jsonify(items)


@match_bp.route("/advanced-search", methods=["GET"])
@login_required
def advanced_search_alias():
    return advanced_search()
