import json
import os
import secrets
from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.db import execute, query_all, query_one
from app.security import build_notification_payload
from app.utils import APIError, add_notification, is_blocked_between, is_match, login_required, update_popularity

profile_bp = Blueprint("profile", __name__)


ALLOWED_GENDERS = {"male", "female", "non_binary"}
ALLOWED_PREFS = {"straight", "gay", "bisexual"}
ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


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


def _update_profile(user_id: int, data):
    """Shared update logic used by both the JSON PUT /profile/me route and the
    plain HTML form on /profile/edit."""
    gender = data.get("gender") or None
    pref = data.get("sexual_preference") or None
    if gender is not None and gender not in ALLOWED_GENDERS:
        raise APIError("Invalid gender", 400)
    if pref is not None and pref not in ALLOWED_PREFS:
        raise APIError("Invalid sexual_preference", 400)

    consent = data.get("location_consent_gps")
    if consent is not None and consent != "":
        consent = bool(consent) if not isinstance(consent, str) else consent.lower() in ("1", "true", "on", "yes")
    else:
        consent = None

    city = data.get("city") or None
    neighborhood = data.get("neighborhood") or None
    latitude = data.get("latitude") or None
    longitude = data.get("longitude") or None

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
            data.get("age") or None,
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
        (data.get("first_name") or None, data.get("last_name") or None, data.get("email") or None, user_id),
    )

    tags = data.get("tags")
    if isinstance(tags, str):
        # Beginner-friendly: a comma-separated text input instead of a tag widget.
        tags = [t for t in tags.split(",")]
    if isinstance(tags, list):
        execute("DELETE FROM user_tags WHERE user_id = ?", (user_id,))
        clean_tags = sorted({str(t).strip().lower() for t in tags if str(t).strip()})
        for tag_name in clean_tags:
            execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))

        if clean_tags:
            placeholders = ",".join(["?"] * len(clean_tags))
            tag_rows = query_all(f"SELECT id FROM tags WHERE name IN ({placeholders})", tuple(clean_tags))
            for tag in tag_rows:
                execute("INSERT OR IGNORE INTO user_tags (user_id, tag_id) VALUES (?, ?)", (user_id, tag["id"]))

    return _profile_payload(user_id)


@profile_bp.route("/profile/me", methods=["GET", "PUT"])
@login_required
def profile_me():
    user_id = g.current_user["id"]

    if request.method == "GET":
        payload = _profile_payload(user_id)
        return jsonify(payload)

    data = request.get_json(silent=True) or request.form
    payload = _update_profile(user_id, data)
    return jsonify(payload)


@profile_bp.route("/profile/edit", methods=["GET"])
@login_required
def edit_profile():
    profile = _profile_payload(g.current_user["id"])
    return render_template("profile_edit.html", profile=profile)


@profile_bp.route("/profile/edit", methods=["POST"])
@login_required
def edit_profile_submit():
    user_id = g.current_user["id"]
    try:
        _update_profile(user_id, request.form)
    except APIError as err:
        flash(err.message, "error")
        return redirect(url_for("profile.edit_profile"))

    flash("Profile updated.", "success")
    return redirect(url_for("profile.edit_profile"))


def _save_uploaded_photo(file_storage):
    filename = secure_filename(file_storage.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in ALLOWED_PHOTO_EXTENSIONS:
        raise APIError("Photo must be one of: png, jpg, jpeg, gif, webp", 400)

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    unique_name = f"{secrets.token_hex(8)}.{ext}"
    file_storage.save(os.path.join(upload_folder, unique_name))

    return f"/static/uploads/{unique_name}"


@profile_bp.route("/profile/me/photos", methods=["POST", "DELETE"])
@login_required
def profile_photos():
    user_id = g.current_user["id"]
    is_form = request.get_json(silent=True) is None and not request.is_json

    if request.method == "POST":
        photo_file = request.files.get("photo")
        if not photo_file or not photo_file.filename:
            if is_form:
                flash("Please choose a photo to upload", "error")
                return redirect(url_for("profile.edit_profile"))
            raise APIError("photo file is required", 400)

        count = query_one("SELECT COUNT(*) AS c FROM photos WHERE user_id = ?", (user_id,))
        if count and count["c"] >= 5:
            if is_form:
                flash("You can upload up to 5 photos", "error")
                return redirect(url_for("profile.edit_profile"))
            raise APIError("You can upload up to 5 photos", 400)

        try:
            url = _save_uploaded_photo(photo_file)
        except APIError as err:
            if is_form:
                flash(err.message, "error")
                return redirect(url_for("profile.edit_profile"))
            raise

        as_primary = bool(request.form.get("is_profile_photo"))
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
            if is_form:
                flash("photo_id is required", "error")
                return redirect(url_for("profile.edit_profile"))
            raise APIError("photo_id is required", 400)

        execute("DELETE FROM photos WHERE id = ? AND user_id = ?", (photo_id, user_id))
        _ensure_primary_photo(user_id)

    if is_form:
        flash("Photo updated.", "success")
        return redirect(url_for("profile.edit_profile"))

    return jsonify(_profile_payload(user_id)["photos"])


@profile_bp.route("/profile/me/photos/delete", methods=["POST"])
@login_required
def profile_photos_delete_form():
    """Plain-HTML-form-friendly wrapper: browsers can't send DELETE from a <form>."""
    user_id = g.current_user["id"]
    photo_id = request.form.get("photo_id")
    if not photo_id:
        flash("photo_id is required", "error")
        return redirect(url_for("profile.edit_profile"))

    execute("DELETE FROM photos WHERE id = ? AND user_id = ?", (photo_id, user_id))
    _ensure_primary_photo(user_id)
    flash("Photo deleted.", "success")
    return redirect(url_for("profile.edit_profile"))


@profile_bp.route("/profile/<int:id>", methods=["GET"])
def detail(id):
    profile = _profile_payload(id)

    if profile is None:
        return "Profile not found", 404

    viewer = g.get("current_user")
    if viewer and viewer["id"] != id:
        if is_blocked_between(viewer["id"], id):
            raise APIError("Profile unavailable", 403)

        recent_view = query_one(
            """
            SELECT id
            FROM profile_views
            WHERE viewer_id = ? AND viewed_id = ? AND created_at >= datetime('now', '-1 day')
            """,
            (viewer["id"], id),
        )
        if not recent_view:
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

    is_form = request.get_json(silent=True) is None and not request.is_json

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

    if is_form:
        return redirect(url_for("profile.detail", id=id))

    return jsonify({
        "liked_by_me": bool(query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (current, id))),
        "liked_me": bool(query_one("SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?", (id, current))),
        "connected": is_match(current, id),
    })


@profile_bp.route("/profile/<int:id>/unlike", methods=["POST"])
@login_required
def unlike_profile_form(id):
    """Plain-HTML-form-friendly wrapper: browsers can't send DELETE from a <form>."""
    current = g.current_user["id"]
    execute("DELETE FROM likes WHERE from_user_id = ? AND to_user_id = ?", (current, id))
    add_notification(id, "unliked", build_notification_payload(from_user_id=current))
    update_popularity(id)
    return redirect(url_for("profile.detail", id=id))


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

    is_form = request.get_json(silent=True) is None and not request.is_json
    if is_form:
        return redirect(url_for("match.browse_view"))

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

    is_form = request.get_json(silent=True) is None and not request.is_json
    if is_form:
        flash("Profile reported.", "success")
        return redirect(url_for("profile.detail", id=id))

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


def _notifications_for(user_id, unread_only=False):
    if unread_only:
        rows = query_all("SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY id DESC LIMIT 100", (user_id,))
    else:
        rows = query_all("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 100", (user_id,))

    payload = []
    for row in rows:
        item = dict(row)
        if item.get("payload"):
            try:
                item["payload"] = json.loads(item["payload"])
            except Exception:
                pass
        payload.append(item)
    return payload


@profile_bp.route("/notifications", methods=["GET"])
@login_required
def list_notifications():
    current = g.current_user["id"]
    unread_only = request.args.get("unread") == "1"
    return jsonify(_notifications_for(current, unread_only))


@profile_bp.route("/notifications/view", methods=["GET"])
@login_required
def notifications_view():
    current = g.current_user["id"]
    notifications = _notifications_for(current)
    return render_template("notifications.html", notifications=notifications)


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

    is_form = request.get_json(silent=True) is None and not request.is_json
    if is_form:
        return redirect(url_for("profile.notifications_view"))

    return jsonify({"ok": True})
