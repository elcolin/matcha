import json
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, render_template, request

from app.db import execute, query_all, query_one
from app.security import build_notification_payload
from app.utils import APIError, add_notification, is_blocked_between, is_match, login_required, update_popularity

profile_bp = Blueprint("profile", __name__)


ALLOWED_GENDERS = {"male", "female", "non_binary"}
ALLOWED_PREFS = {"straight", "gay", "bisexual"}


def _profile_payload(user_id: int):
    row = query_one(
        """
        SELECT u.id, u.username, u.first_name, u.last_name, u.last_seen_at, u.online_until,
               p.gender, p.sexual_preference, p.bio, p.city, p.neighborhood,
               p.latitude, p.longitude, p.location_consent_gps, p.popularity_score, p.age
        FROM users u
        JOIN profiles p ON p.user_id = u.id
        WHERE u.id = ?
        """,
        (user_id,),
    )

    if not row:
        return None

    tags = query_all(
        """
        SELECT t.name
        FROM user_tags ut
        JOIN tags t ON t.id = ut.tag_id
        WHERE ut.user_id = ?
        ORDER BY t.name ASC
        """,
        (user_id,),
    )

    photos = query_all(
        "SELECT id, url, is_profile_photo FROM photos WHERE user_id = ? ORDER BY is_profile_photo DESC, id ASC",
        (user_id,),
    )

    online = False
    if row["online_until"]:
        online = datetime.fromisoformat(row["online_until"]) > datetime.now(timezone.utc)

    return {
        "id": row["id"],
        "username": row["username"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "gender": row["gender"],
        "sexual_preference": row["sexual_preference"] or "bisexual",
        "bio": row["bio"] or "",
        "city": row["city"],
        "neighborhood": row["neighborhood"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "location_consent_gps": bool(row["location_consent_gps"]),
        "popularity_score": row["popularity_score"],
        "age": row["age"],
        "online": online,
        "last_seen_at": row["last_seen_at"],
        "tags": [r["name"] for r in tags],
        "photos": [dict(r) for r in photos],
    }


def _ensure_primary_photo(user_id: int):
    profile_photo = query_one("SELECT id FROM photos WHERE user_id = ? AND is_profile_photo = 1", (user_id,))
    if profile_photo:
        return

    first = query_one("SELECT id FROM photos WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
    if first:
        execute("UPDATE photos SET is_profile_photo = 1 WHERE id = ?", (first["id"],))


@profile_bp.route("/profile/me", methods=["GET", "PUT"])
@login_required
def profile_me():
    user_id = g.current_user["id"]

    if request.method == "GET":
        payload = _profile_payload(user_id)
        return jsonify(payload)

    data = request.get_json(silent=True) or request.form

    gender = data.get("gender")
    pref = data.get("sexual_preference")
    if gender is not None and gender not in ALLOWED_GENDERS:
        raise APIError("Invalid gender", 400)
    if pref is not None and pref not in ALLOWED_PREFS:
        raise APIError("Invalid sexual_preference", 400)

    consent = data.get("location_consent_gps")
    if consent is not None:
        consent = bool(consent)

    city = data.get("city")
    neighborhood = data.get("neighborhood")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if consent is False and not (city or neighborhood):
        raise APIError("Manual location (city or neighborhood) is required when GPS consent is refused", 400)

    execute(
        """
        UPDATE profiles
        SET gender = COALESCE(?, gender),
            sexual_preference = COALESCE(?, sexual_preference),
            bio = COALESCE(?, bio),
            city = COALESCE(?, city),
            neighborhood = COALESCE(?, neighborhood),
            latitude = COALESCE(?, latitude),
            longitude = COALESCE(?, longitude),
            location_consent_gps = COALESCE(?, location_consent_gps),
            age = COALESCE(?, age),
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (
            gender,
            pref,
            data.get("bio"),
            city,
            neighborhood,
            latitude,
            longitude,
            int(consent) if consent is not None else None,
            data.get("age"),
            user_id,
        ),
    )

    # User core fields updates
    execute(
        """
        UPDATE users
        SET first_name = COALESCE(?, first_name),
            last_name = COALESCE(?, last_name),
            email = COALESCE(?, email)
        WHERE id = ?
        """,
        (data.get("first_name"), data.get("last_name"), data.get("email"), user_id),
    )

    tags = data.get("tags")
    if isinstance(tags, list):
        execute("DELETE FROM user_tags WHERE user_id = ?", (user_id,))
        for tag_name in {str(t).strip().lower() for t in tags if str(t).strip()}:
            execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
            tag = query_one("SELECT id FROM tags WHERE name = ?", (tag_name,))
            execute("INSERT OR IGNORE INTO user_tags (user_id, tag_id) VALUES (?, ?)", (user_id, tag["id"]))

    return jsonify(_profile_payload(user_id))


@profile_bp.route("/profile/me/photos", methods=["POST", "DELETE"])
@login_required
def profile_photos():
    user_id = g.current_user["id"]

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        url = str(data.get("url", "")).strip()
        as_primary = bool(data.get("is_profile_photo", False))

        if not url:
            raise APIError("url is required", 400)

        count = query_one("SELECT COUNT(*) AS c FROM photos WHERE user_id = ?", (user_id,))
        if count and count["c"] >= 5:
            raise APIError("You can upload up to 5 photos", 400)

        if as_primary:
            execute("UPDATE photos SET is_profile_photo = 0 WHERE user_id = ?", (user_id,))

        execute(
            "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, ?, ?)",
            (user_id, url, int(as_primary)),
        )
        _ensure_primary_photo(user_id)

    else:
        data = request.get_json(silent=True) or request.form
        photo_id = data.get("photo_id")
        if not photo_id:
            raise APIError("photo_id is required", 400)

        execute("DELETE FROM photos WHERE id = ? AND user_id = ?", (photo_id, user_id))
        _ensure_primary_photo(user_id)

    return jsonify(_profile_payload(user_id)["photos"])


@profile_bp.route("/profile/<int:id>", methods=["GET"])
def detail(id):
    profile = _profile_payload(id)

    if profile is None:
        return "Profile not found", 404

    viewer = g.get("current_user")
    if viewer and viewer["id"] != id:
        if is_blocked_between(viewer["id"], id):
            raise APIError("Profile unavailable", 403)

        execute("INSERT INTO profile_views (viewer_id, viewed_id) VALUES (?, ?)", (viewer["id"], id))
        add_notification(id, "profile_view", build_notification_payload(viewer_id=viewer["id"]))
        update_popularity(id)

        profile["liked_by_me"] = bool(query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (viewer["id"], id)))
        profile["liked_me"] = bool(query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (id, viewer["id"])))
        profile["connected"] = is_match(viewer["id"], id)

    if request.args.get("format") == "json":
        profile.pop("email", None)
        return jsonify(profile)

    profile["name"] = f"{profile['first_name']} {profile['last_name']}".strip()
    profile["image"] = (
        profile["photos"][0]["url"]
        if profile["photos"]
        else "https://placehold.co/600x400?text=Matcha"
    )
    profile["interests"] = profile.get("tags", [])

    return render_template("profile.html", profile=profile)


@profile_bp.route("/profile/<int:id>/like", methods=["POST", "DELETE"])
@login_required
def like_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot like yourself", 400)

    if is_blocked_between(current, id):
        raise APIError("Interaction unavailable", 403)

    my_photo = query_one("SELECT 1 FROM photos WHERE user_id = ? AND is_profile_photo = 1", (current,))
    if not my_photo:
        raise APIError("You need a profile photo to like someone", 400)

    if request.method == "POST":
        execute("INSERT OR IGNORE INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (current, id))
        add_notification(id, "like_received", build_notification_payload(from_user_id=current))

        if is_match(current, id):
            add_notification(id, "new_match", build_notification_payload(user_id=current))
            add_notification(current, "new_match", build_notification_payload(user_id=id))

    else:
        execute("DELETE FROM likes WHERE from_user_id = ? AND to_user_id = ?", (current, id))
        add_notification(id, "unliked", build_notification_payload(from_user_id=current))

    update_popularity(id)

    return jsonify({
        "liked_by_me": bool(query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (current, id))),
        "liked_me": bool(query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (id, current))),
        "connected": is_match(current, id),
    })


@profile_bp.route("/profile/<int:id>/block", methods=["POST", "DELETE"])
@login_required
def block_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot block yourself", 400)

    if request.method == "POST":
        execute("INSERT OR IGNORE INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (current, id))
    else:
        execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (current, id))

    return jsonify({"blocked": bool(query_one("SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (current, id)))})


@profile_bp.route("/profile/<int:id>/report", methods=["POST"])
@login_required
def report_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot report yourself", 400)

    execute(
        "INSERT OR REPLACE INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, 'fake_account')",
        (current, id),
    )
    update_popularity(id)
    return jsonify({"reported": True})


@profile_bp.route("/profile/me/viewers", methods=["GET"])
@login_required
def my_viewers():
    current = g.current_user["id"]
    rows = query_all(
        """
        SELECT u.id, u.username, u.first_name, u.last_name, MAX(v.created_at) AS last_view_at
        FROM profile_views v
        JOIN users u ON u.id = v.viewer_id
        WHERE v.viewed_id = ?
        GROUP BY u.id, u.username, u.first_name, u.last_name
        ORDER BY last_view_at DESC
        """,
        (current,),
    )
    return jsonify([dict(r) for r in rows])


@profile_bp.route("/profile/me/liked-by", methods=["GET"])
@login_required
def liked_by_me():
    current = g.current_user["id"]
    rows = query_all(
        """
        SELECT u.id, u.username, u.first_name, u.last_name, l.created_at
        FROM likes l
        JOIN users u ON u.id = l.from_user_id
        WHERE l.to_user_id = ?
        ORDER BY l.created_at DESC
        """,
        (current,),
    )
    return jsonify([dict(r) for r in rows])


@profile_bp.route("/notifications", methods=["GET"])
@login_required
def list_notifications():
    current = g.current_user["id"]
    unread_only = request.args.get("unread") == "1"
    if unread_only:
        rows = query_all("SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY id DESC LIMIT 100", (current,))
    else:
        rows = query_all("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100", (current,))

    payload = []
    for row in rows:
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
        payload.append(item)

    return jsonify(payload)


@profile_bp.route("/notifications/unread-count", methods=["GET"])
@login_required
def unread_notifications_count():
    current = g.current_user["id"]
    row = query_one("SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0", (current,))
    return jsonify({"unread": row["c"] if row else 0})


@profile_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    current = g.current_user["id"]
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current,))
    return jsonify({"ok": True})
