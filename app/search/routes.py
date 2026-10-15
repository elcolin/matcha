from flask import Blueprint, g, render_template, request

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
        if min_age is not None and p.get("age", 0) < min_age:
            return False
        if max_age is not None and p.get("age", 0) > max_age:
            return False
        if min_pop is not None and p.get("popularity_score", 0) < min_pop:
            return False
        if max_pop is not None and p.get("popularity_score", 0) > max_pop:
            return False
        if city and (p.get("city") or "").lower() != city:
            return False
        if required_tags and not required_tags <= {t.lower() for t in p.get("tags", [])}:
            return False
        return True

    return [p for p in items if ok(p)]


def _sort(items, args):
    keys = {
        "age": lambda p: p.get("age", 0),
        "location": lambda p: p["distance_km"],
        "popularity": lambda p: p.get("popularity_score", 0),
        "tags": lambda p: p["shared_tags_count"],
    }
    sort_by = args.get("sort_by", "smart")
    if sort_by in keys:  # "smart" keeps the order from candidate_profiles()
        items.sort(key=keys[sort_by], reverse=args.get("order", "desc") == "desc")
    return items


@search_bp.route("/search", methods=["GET"])
@login_required
def search_view():
    searched = bool(request.args)  # the form always sends sort_by/order, so any submit counts
    profiles = []
    if searched:
        profiles = candidate_profiles(g.current_user["id"])
        profiles = _sort(_filter(profiles, request.args), request.args)[:50]
        for p in profiles:  # hide the placeholder distance for users without GPS
            if p["distance_km"] >= MISSING_DISTANCE_KM:
                p["distance_km"] = None
    return render_template("search.html", profiles=profiles, searched=searched, args=request.args)