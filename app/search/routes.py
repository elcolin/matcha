from flask import Blueprint, g, render_template, request
from app.db import query_one
from app.match.routes import MISSING_DISTANCE_KM, candidate_profiles
from app.utils import login_required

search_bp = Blueprint("search", __name__)


def _filter(items, args):
    min_age = args.get("min_age", type=int)
    max_age = args.get("max_age", type=int)
    min_pop = args.get("min_popularity", type=int)
    max_pop = args.get("max_popularity", type=int)
    city = args.get("city", "").strip().lower()
    required_tags = {t.strip().lower() for t in args.get("tags", "").split(",") if t.strip()}
    
    def ok(p):
        age = p.get("age")
        popularity = p.get("popularity_score") or 0

        if min_age is not None and (age is None or age < min_age):
            return False
        if max_age is not None and (age is None or age > max_age):
            return False
        if min_pop is not None and popularity < min_pop:
            return False
        if max_pop is not None and popularity > max_pop:
            return False
        if city and (p.get("city") or "").lower() != city:
            return False
        if required_tags and not required_tags <= {t.lower() for t in p.get("tags", [])}:
            return False
        return True

    return [p for p in items if ok(p)]


def _non_negative(args, name):
    value = args.get(name, type=int)
    return value if value is not None and value >= 0 else None


def _refine(items, args, viewer_age):
    """Result filters relative to the viewer (no ranges: those are search criteria)."""
    age_gap = _non_negative(args, "age_gap")
    max_distance = _non_negative(args, "max_distance")
    min_fame = _non_negative(args, "min_fame")
    min_shared = _non_negative(args, "min_shared_tags")

    def ok(p):
        if age_gap is not None and viewer_age is not None:
            if p.get("age") is None or abs(p["age"] - viewer_age) > age_gap:
                return False
        if max_distance is not None and p.get("distance_km", MISSING_DISTANCE_KM) > max_distance:
            return False
        if min_fame is not None and (p.get("popularity_score") or 0) < min_fame:
            return False
        if min_shared is not None and p.get("shared_tags_count", 0) < min_shared:
            return False
        return True

    return [p for p in items if ok(p)]


def _sort(items, args):
    keys = {
        "age": lambda p: p.get("age") or 0,
        "location": lambda p: p["distance_km"],
        "popularity": lambda p: p.get("popularity_score", 0),
        "tags": lambda p: p["shared_tags_count"],
    }
    descending = args.get("order", "desc") != "asc"
    sort_by = args.get("sort_by", "smart")
    if sort_by == "location":
        known = [
            p for p in items
            if p.get("distance_km") is not None and p["distance_km"] < MISSING_DISTANCE_KM
        ]
        unknown = [
            p for p in items
            if p.get("distance_km") is None or p["distance_km"] >= MISSING_DISTANCE_KM
        ]
        known.sort(key=keys[sort_by], reverse=descending)
        items[:] = known + unknown
    elif sort_by in keys:
        items.sort(key=keys[sort_by], reverse=descending)
    elif not descending:  # "smart": candidate_profiles() ranks best matches first
        items.reverse()
    return items


def filtered_profiles(viewer_id, args, limit, with_criteria):
    """Suggestions for viewer_id, refined and sorted by the query args.
    with_criteria also applies the advanced-search range criteria."""
    profiles = candidate_profiles(viewer_id)
    if with_criteria:
        profiles = _filter(profiles, args)
    viewer = query_one("SELECT age FROM profiles WHERE user_id = ?", (viewer_id,))
    profiles = _refine(profiles, args, viewer["age"] if viewer else None)
    profiles = _sort(profiles, args)[:limit]
    for p in profiles:
        if p["distance_km"] >= MISSING_DISTANCE_KM:
            p["distance_km"] = None
    return profiles


@search_bp.route("/search", methods=["GET"])
@login_required
def search_view():
    searched = bool(request.args)
    profiles = filtered_profiles(g.current_user["id"], request.args, 50, with_criteria=True) if searched else []

    return render_template(
        "search.html",
        profiles=profiles,
        searched=searched,
        args=request.args,
    )
