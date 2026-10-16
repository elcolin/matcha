import math
import io
import secrets
import os
import threading
import warnings
from datetime import datetime, timezone

from app.config import UserConfig
from .data import UserUpdater
from .geolocation import get_location_from_coords, geocode_city

from flask import (
    Blueprint,
    g,
    jsonify,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)

from PIL import Image, ImageOps, ImageSequence
from werkzeug.utils import secure_filename

from app.db import execute, query_all, query_one
from app.email import send_email
from app.security import build_notification_payload
from app.utils import (
    APIError,
    add_notification,
    is_blocked_between,
    is_match,
    login_required,
    update_popularity,
)

profile_bp = Blueprint("profile", __name__, url_prefix="/profile")


def _is_form_request():
    """True for a plain HTML form submission (vs. a JSON API call).

    Header-based only: it must never read the body, since it is also used by
    the 413 handler in app/__init__.py where reading the body would re-raise.
    """
    return not request.is_json


def _compute_online(online_until: str | None) -> bool:
    """True if `online_until` (ISO timestamp, see app/__init__.py) is in the future."""
    if not online_until:
        return False
    return datetime.fromisoformat(online_until) > datetime.now(timezone.utc)


def _profile_payload(user_id: int, include_email: bool = False, include_coordinates: bool = False):
    """Build the profile dict shared by the profile/edit/match/chat views.

    `email` and the exact `latitude`/`longitude` are deliberately left out
    unless `include_email=True` / `include_coordinates=True` is passed
    explicitly by an owner-only or internal call site (e.g. GET /profile/edit,
    distance computation in candidate_profiles): this payload is also used for
    third-party profiles (candidate suggestions, profile detail of another
    user), which must never expose someone else's email address or precise
    location.
    """
    row = query_one(
        """
        SELECT u.id, u.username, u.email, u.first_name, u.last_name, u.last_seen_at, u.online_until,
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

    return _build_profile_payload(
        row,
        [r["name"] for r in tags],
        [dict(r) for r in photos],
        include_email=include_email,
        include_coordinates=include_coordinates,
    )


def _build_profile_payload(row, tags, photos, include_email: bool = False, include_coordinates: bool = False):
    """Shape a users+profiles row into the profile dict (no DB access).

    `tags` is a list of tag names (sorted by name), `photos` a list of
    {id, url, is_profile_photo} dicts (profile photo first, then by id).
    """
    payload = {
        "id": row["id"],
        "username": row["username"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "gender": row["gender"],
        "sexual_preference": row["sexual_preference"] or "everyone",
        "bio": row["bio"] or "",
        "city": row["city"],
        "neighborhood": row["neighborhood"],
        "location_consent_gps": bool(row["location_consent_gps"]),
        "popularity_score": row["popularity_score"],
        "age": row["age"],
        "online": _compute_online(row["online_until"]),
        "last_seen_at": row["last_seen_at"],
        "tags": tags,
        "photos": photos,
    }

    if include_email:
        payload["email"] = row["email"]

    if include_coordinates:
        payload["latitude"] = row["latitude"]
        payload["longitude"] = row["longitude"]

    return payload


def _ensure_primary_photo(user_id: int):
    profile_photo = query_one(
        "SELECT id FROM photos WHERE user_id = ? AND is_profile_photo = 1", (user_id,)
    )
    if profile_photo:
        return

    first = query_one(
        "SELECT id FROM photos WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,)
    )
    if first:
        execute("UPDATE photos SET is_profile_photo = 1 WHERE id = ?", (first["id"],))


def _delete_user_photo(user_id: int, photo_id):
    """Delete one of `user_id`'s photos: DB row, uploaded file (if local), then
    reassign the profile photo. A foreign or unknown `photo_id` is a no-op."""
    row = query_one(
        "SELECT url FROM photos WHERE id = ? AND user_id = ?",
        (photo_id, user_id),
    )
    execute("DELETE FROM photos WHERE id = ? AND user_id = ?", (photo_id, user_id))
    if row and row["url"].startswith("/static/uploads/"):
        try:
            os.remove(
                os.path.join(
                    current_app.config["UPLOAD_FOLDER"],
                    os.path.basename(row["url"]),
                )
            )
        except FileNotFoundError:
            pass
    _ensure_primary_photo(user_id)


def _pending_email_change(user_id: int):
    """Return the active (not used, not expired) email_changes row for this
    user, if any, so profile_edit.html can tell the user a confirmation is
    still pending (see app.auth.routes.confirm_email_change)."""
    return query_one(
        """
        SELECT new_email
        FROM email_changes
        WHERE user_id = ? AND used_at IS NULL AND expires_at > ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, datetime.now(timezone.utc).isoformat()),
    )


@profile_bp.route("/edit", methods=["GET"])
@login_required
def edit_profile():
    profile = _profile_payload(g.current_user["id"], include_email=True, include_coordinates=True)
    pending_email_change = _pending_email_change(g.current_user["id"])
    return render_template(
        "profile_edit.html",
        profile=profile,
        pending_email_change=pending_email_change,
        max_upload_bytes=current_app.config["MAX_CONTENT_LENGTH"],
    )

LOCATION_FORM_KEYS = ("city", "neighborhood", "latitude", "longitude")


def _parse_coordinate(value, limit):
    """Return `value` as a finite float within [-limit, limit], else None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not -limit <= number <= limit:
        return None
    return number


def _parse_consent(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes")
    return bool(value)


COORD_TOLERANCE = 1e-6


def _normalize_place(value):
    """Comparison key for a city/neighborhood: trimmed, case-insensitive, '' == None."""
    return (value or "").strip().lower() or None


def _same_coordinate(a, b):
    return a is not None and b is not None and abs(a - b) <= COORD_TOLERANCE


def _resolve_location(user_id, data):
    """Validate the submitted location and resolve it through the geocoder.

    GPS consent: reverse-geocode the submitted coordinates to a city.
    Manual mode: city is required, coordinates come from forward geocoding
    (any submitted lat/lon is ignored). An unchanged location (same mode and
    same place or coordinates as stored) reuses the stored resolution without
    calling the geocoder. Raises APIError, never writes.
    """
    stored = query_one(
        "SELECT city, neighborhood, latitude, longitude, location_consent_gps "
        "FROM profiles WHERE user_id = ?",
        (user_id,),
    )
    consent = _parse_consent(data.get("location_consent_gps"))
    stored_consent = bool(stored and stored["location_consent_gps"])
    if consent:
        latitude = _parse_coordinate(data.get("latitude"), 90)
        longitude = _parse_coordinate(data.get("longitude"), 180)
        if latitude is None or longitude is None:
            raise APIError(
                "Your GPS position is missing or invalid, please enter your city manually.", 400
            )
        if (
            stored_consent
            and stored["city"]
            and _same_coordinate(latitude, stored["latitude"])
            and _same_coordinate(longitude, stored["longitude"])
        ):
            # Same fix as stored (within tolerance): keep the stored row as is.
            city, neighborhood = stored["city"], stored["neighborhood"]
            latitude, longitude = stored["latitude"], stored["longitude"]
        else:
            result = get_location_from_coords(latitude, longitude)
            city, neighborhood = result["city"], result["neighbourhood"] or None
    else:
        city = (data.get("city") or "").strip()
        neighborhood = (data.get("neighborhood") or "").strip() or None
        if not city:
            raise APIError("Please enter your city.", 400)
        if (
            stored
            and not stored_consent
            and stored["latitude"] is not None
            and stored["longitude"] is not None
            and _normalize_place(city) == _normalize_place(stored["city"])
            and _normalize_place(neighborhood) == _normalize_place(stored["neighborhood"])
        ):
            latitude, longitude = stored["latitude"], stored["longitude"]
        else:
            latitude, longitude = geocode_city(city, neighborhood)

    return {
        "city": city,
        "neighborhood": neighborhood,
        "latitude": latitude,
        "longitude": longitude,
        "consent": int(consent),
    }


def _update_profile(user_id: int, data):
    """Shared update logic used by the plain HTML form on /profile/edit."""
    gender = data.get("gender") or None
    pref = data.get("sexual_preference") or None
    if gender is not None and gender not in UserConfig.GENDERS:
        raise APIError("Invalid gender", 400)
    if pref is not None and pref not in UserConfig.SEXUAL_PREFERENCES:
        raise APIError("Invalid sexual_preference", 400)

    # Location is fully resolved (validation + geocoding) before any write so
    # that a geocoder failure aborts the whole update, leaving the row as is.
    location = _resolve_location(user_id, data) if "location_consent_gps" in data else None

    # City, neighborhood and coordinates are written together (explicitly, not
    # COALESCE, so a cleared neighborhood does not keep a stale value) only
    # when the location was submitted; otherwise the stored ones are kept.
    has_location = location is not None
    location = location or {}
    execute(
        """
        UPDATE profiles
        SET gender = COALESCE(?, gender),
            sexual_preference = COALESCE(?, sexual_preference),
            bio = COALESCE(?, bio),
            age = COALESCE(?, age),
            city = CASE WHEN ? THEN ? ELSE city END,
            neighborhood = CASE WHEN ? THEN ? ELSE neighborhood END,
            latitude = CASE WHEN ? THEN ? ELSE latitude END,
            longitude = CASE WHEN ? THEN ? ELSE longitude END,
            location_consent_gps = CASE WHEN ? THEN ? ELSE location_consent_gps END,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (
            gender,
            pref,
            data.get("bio"),
            data.get("age") or None,
            has_location, location.get("city"),
            has_location, location.get("neighborhood"),
            has_location, location.get("latitude"),
            has_location, location.get("longitude"),
            has_location, location.get("consent"),
            user_id,
        ),
    )

    UserUpdater.change_users_first_name(user_id, data.get("first_name") or None)
    UserUpdater.change_users_lastname(user_id, data.get("last_name") or None)

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
            tag_rows = query_all(
                f"SELECT id FROM tags WHERE name IN ({placeholders})", tuple(clean_tags)
            )
            for tag in tag_rows:
                execute(
                    "INSERT OR IGNORE INTO user_tags (user_id, tag_id) VALUES (?, ?)",
                    (user_id, tag["id"]),
                )

    return _profile_payload(user_id)


def _request_email_change_and_notify(user_id: int, new_email):
    """Start a deferred email change and email the confirmation link to the
    NEW address; the active email is only updated once that link is clicked
    (see app.auth.routes.confirm_email_change). No-op if `new_email` is
    empty.

    Always flashes the same generic message regardless of whether the
    change actually resulted in a token being issued (matches current
    active email, or already used by another account): the observable
    response must never reveal whether an email address is already
    registered (enumeration - see fix/password-reset-enumeration for the
    same pattern applied to the password reset flow).
    """
    if not new_email:
        return

    token = UserUpdater.request_email_change(
        user_id,
        new_email,
        current_app.config["SECRET_KEY"],
        current_app.config["EMAIL_CHANGE_TOKEN_TTL_SECONDS"],
    )

    if token:
        pending = query_one("SELECT new_email FROM email_changes WHERE token = ?", (token,))
        confirm_link = url_for("auth.confirm_email_change", token=token, _external=True)
        try:
            send_email(
                pending["new_email"],
                "Confirm your new Matcha email address",
                f"""
                <h1>Confirm your new email address</h1>
                <p>You asked to change the email address linked to your Matcha account.</p>
                <p><a href="{confirm_link}">Confirm this change</a></p>
                <p>If you did not request this, ignore this email: your current address stays active.</p>
                """,
            )
        except Exception:
            # Never let an SMTP failure surface as a 500, and never log the
            # raw email address (see CLAUDE.md: no secret/PII in logs).
            current_app.logger.exception(
                "Failed to send email change confirmation to user %s", user_id
            )

    flash(
        "If this address is valid, a confirmation email has been sent.",
        "success",
    )


@profile_bp.route("/edit", methods=["POST"])
@login_required
def edit_profile_submit():
    user_id = g.current_user["id"]
    try:
        form_data = request.form.to_dict(flat=True)
        # An unchecked checkbox is not submitted: treat it as "manual mode",
        # but only when the location part of the form was actually posted so
        # partial submissions (e.g. name/email only) leave location untouched.
        if any(key in form_data for key in LOCATION_FORM_KEYS):
            form_data.setdefault("location_consent_gps", "0")
        _update_profile(user_id, form_data)
        _request_email_change_and_notify(user_id, form_data.get("email") or None)
    except APIError as err:
        flash(err.message, "error")
        return redirect(url_for("profile.edit_profile"))

    flash("Profile updated.", "success")
    return redirect(url_for("profile.edit_profile"))

ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
PHOTO_FORMAT_ERROR = "Photo must be a PNG, JPEG, GIF or WebP image"


# Process-global Pillow setting: images above this pixel count trigger a
# DecompressionBombWarning (rejected below), above twice it an error.
Image.MAX_IMAGE_PIXELS = 25_000_000
MAX_PHOTO_FRAMES = 100
# Multi-picture JPEGs (MPF, common on phones) open as "MPO": only their
# primary image is kept, stored as a plain JPEG.
PHOTO_FORMAT_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "MPO": "jpg", "GIF": "gif", "WEBP": "webp"}
# Only rendering-related info survives re-encoding (no EXIF/GPS, ICC, comments...).
PHOTO_FRAME_INFO_KEYS = ("transparency", "duration")
# warnings.catch_warnings() swaps process-global state: concurrent uploads
# (threaded server) must not interleave it.
_WARNINGS_CAPTURE_LOCK = threading.Lock()


def _reencode_photo(data):
    """Fully decode an uploaded image and re-encode it without metadata.

    Returns (bytes, extension); raises APIError if the content is not a
    complete, reasonably sized PNG/JPEG/GIF/WebP image.
    """
    try:
        with _WARNINGS_CAPTURE_LOCK, warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with Image.open(io.BytesIO(data)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(data)) as img:
                if any(issubclass(w.category, Image.DecompressionBombWarning) for w in caught):
                    raise APIError(PHOTO_FORMAT_ERROR, 400)
                ext = PHOTO_FORMAT_EXTENSIONS.get(img.format)
                n_frames = getattr(img, "n_frames", 1)
                total_pixels = img.width * img.height * n_frames
                if ext is None or n_frames > MAX_PHOTO_FRAMES or total_pixels > Image.MAX_IMAGE_PIXELS:
                    raise APIError(PHOTO_FORMAT_ERROR, 400)

                out_format = "JPEG" if img.format == "MPO" else img.format
                sources = [img] if img.format == "MPO" else ImageSequence.Iterator(img)
                frames = []
                for frame in sources:
                    frame = ImageOps.exif_transpose(frame)
                    if ext == "jpg" and frame.mode not in ("RGB", "L"):
                        frame = frame.convert("RGB")
                    frame.info = {k: frame.info[k] for k in PHOTO_FRAME_INFO_KEYS if k in frame.info}
                    frames.append(frame)

                out = io.BytesIO()
                if len(frames) > 1:
                    frames[0].save(
                        out,
                        format=out_format,
                        save_all=True,
                        append_images=frames[1:],
                        duration=[f.info.get("duration", 100) for f in frames],
                        loop=img.info.get("loop", 0),
                    )
                else:
                    frames[0].save(out, format=out_format)
    except APIError:
        raise
    except Exception:
        # Pillow does not guarantee its exception set on malformed input
        # (e.g. struct.error): any decode failure is an invalid photo.
        raise APIError(PHOTO_FORMAT_ERROR, 400)
    return out.getvalue(), ext


def _save_uploaded_photo(file_storage):
    filename = secure_filename(file_storage.filename or "")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in ALLOWED_PHOTO_EXTENSIONS:
        raise APIError(PHOTO_FORMAT_ERROR, 400)

    # The client filename/extension is untrusted: the stored content and
    # extension come from decoding and re-encoding the actual image.
    content, detected_ext = _reencode_photo(file_storage.stream.read())

    upload_folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    unique_name = f"{secrets.token_hex(8)}.{detected_ext}"
    with open(os.path.join(upload_folder, unique_name), "wb") as fh:
        fh.write(content)

    return f"/static/uploads/{unique_name}"


@profile_bp.route("/edit/photos", methods=["POST", "DELETE"])
@login_required
def profile_photos():
    user_id = g.current_user["id"]
    is_form = _is_form_request()

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
        _delete_user_photo(user_id, photo_id)

    if is_form:
        flash("Photo updated.", "success")
        return redirect(url_for("profile.edit_profile"))

    return jsonify(_profile_payload(user_id)["photos"])


@profile_bp.route("/edit/photos/delete", methods=["POST"])
@login_required
def profile_photos_delete_form():
    """Plain-HTML-form-friendly wrapper: browsers can't send DELETE from a <form>."""
    user_id = g.current_user["id"]
    photo_id = request.form.get("photo_id")
    if not photo_id:
        flash("photo_id is required", "error")
        return redirect(url_for("profile.edit_profile"))

    _delete_user_photo(user_id, photo_id)
    flash("Photo deleted.", "success")
    return redirect(url_for("profile.edit_profile"))


@profile_bp.route("/<int:id>", methods=["GET"])
@login_required
def detail(id):
    profile = _profile_payload(id)

    if profile is None:
        return "Profile not found", 404

    viewer = g.current_user
    is_self = viewer["id"] == id
    profile["is_self"] = is_self
    if not is_self:

        if not is_blocked_between(viewer["id"], id):
            recent_view = query_one(
                """
                SELECT id
                FROM profile_views
                WHERE viewer_id = ? AND viewed_id = ? AND created_at >= datetime('now', '-1 day')
                """,
                (viewer["id"], id),
            )
            if not recent_view:
                execute(
                    "INSERT INTO profile_views (viewer_id, viewed_id) VALUES (?, ?)",
                    (viewer["id"], id),
                )
                add_notification(
                    id, "profile_view", build_notification_payload(viewer_id=viewer["id"])
                )
                update_popularity(id)

        profile["liked_by_me"] = bool(
            query_one(
                "SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?",
                (viewer["id"], id),
            )
        )
        profile["liked_me"] = bool(
            query_one(
                "SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?",
                (id, viewer["id"]),
            )
        )
        profile["connected"] = is_match(viewer["id"], id)
        profile["blocked_by_me"] = bool(
            query_one(
                "SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?)",
                (viewer["id"], id),
            )
        )
        profile["blocked_me"] = bool(
            query_one(
                "SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?)",
                (id, viewer["id"]),
            )
        )
        profile["reported_by_me"] = bool(
            query_one(
                "SELECT 1 FROM reports WHERE reporter_id = ? AND reported_id = ?",
                (viewer["id"], id),
            )
        )

    if request.args.get("format") == "json":
        return jsonify(profile)

    profile["name"] = f"{profile['first_name']} {profile['last_name']}".strip()
    profile["image"] = (
        profile["photos"][0]["url"]
        if profile["photos"]
        else "https://placehold.co/600x400?text=Matcha"
    )
    profile["interests"] = profile.get("tags", [])

    return render_template("profile.html", profile=profile)


@profile_bp.route("/<int:id>/like", methods=["POST", "DELETE"])
@login_required
def like_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot like yourself", 400)

    if is_blocked_between(current, id):
        raise APIError("Interaction unavailable", 403)

    my_photo = query_one(
        "SELECT 1 FROM photos WHERE user_id = ? AND is_profile_photo = 1", (current,)
    )
    if not my_photo:
        raise APIError("You need a profile photo to like someone", 400)

    is_form = _is_form_request()
    if request.method == "POST":
        execute(
            "INSERT OR IGNORE INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (current, id),
        )
        add_notification(
            id, "like_received", build_notification_payload(from_user_id=current)
        )

        if is_match(current, id):
            add_notification(
                id, "new_match", build_notification_payload(user_id=current)
            )
            add_notification(
                current, "new_match", build_notification_payload(user_id=id)
            )

    else:
        execute(
            "DELETE FROM likes WHERE from_user_id = ? AND to_user_id = ?", (current, id)
        )
        add_notification(
            id, "unliked", build_notification_payload(from_user_id=current)
        )

    update_popularity(id)

    if is_form:
        return redirect(url_for("profile.detail", id=id))

    return jsonify(
        {
            "liked_by_me": bool(
                query_one(
                    "SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?",
                    (current, id),
                )
            ),
            "liked_me": bool(
                query_one(
                    "SELECT 1 FROM likes WHERE from_user_id = ? AND to_user_id = ?",
                    (id, current),
                )
            ),
            "connected": is_match(current, id),
        }
    )


@profile_bp.route("/<int:id>/unlike", methods=["POST"])
@login_required
def unlike_profile_form(id):
    """Plain-HTML-form-friendly wrapper: browsers can't send DELETE from a <form>."""
    current = g.current_user["id"]
    cur = execute(
        "DELETE FROM likes WHERE from_user_id = ? AND to_user_id = ?", (current, id)
    )
    if cur.rowcount:
        if not is_blocked_between(current, id):
            add_notification(
                id, "unliked", build_notification_payload(from_user_id=current)
            )
        update_popularity(id)
    return redirect(url_for("profile.detail", id=id))


@profile_bp.route("/<int:id>/unblock", methods=["POST"])
@login_required
def unblock_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot unblock yourself", 400)

    execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (current, id))

    is_form = _is_form_request()
    if is_form:
        return redirect(url_for("profile.detail", id=id))

    return jsonify(
        {
            "blocked": bool(
                query_one(
                    "SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                    (current, id),
                )
            )
        }
    )


@profile_bp.route("/<int:id>/block", methods=["POST", "DELETE"])
@login_required
def block_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot block yourself", 400)

    if request.method == "DELETE":
        execute(
            "DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (current, id)
        )
        return jsonify(
            {
                "blocked": bool(
                    query_one(
                        "SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                        (current, id),
                    )
                )
            }
        )

    execute(
        "INSERT OR IGNORE INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
        (current, id),
    )
    execute(
        "DELETE FROM likes WHERE (from_user_id = ? AND to_user_id = ?) OR (from_user_id = ? AND to_user_id = ?)",
        (current, id, id, current),
    )
    update_popularity(id)
    update_popularity(current)
    is_form = _is_form_request()
    if is_form:
        return redirect(url_for("profile.detail", id=id))

    return jsonify(
        {
            "blocked": bool(
                query_one(
                    "SELECT 1 FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
                    (current, id),
                )
            )
        }
    )


@profile_bp.route("/<int:id>/report", methods=["POST"])
@login_required
def report_profile(id):
    current = g.current_user["id"]
    if current == id:
        raise APIError("Cannot report yourself", 400)
    if not query_one("SELECT 1 FROM users WHERE id = ?", (id,)):
        raise APIError("Profile not found", 404)

    execute(
        "INSERT OR IGNORE INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, 'fake_account')",
        (current, id),
    )
    update_popularity(id)
    is_form = _is_form_request()
    if is_form:
        flash("Profile reported.", "success")
        return redirect(url_for("profile.detail", id=id))
    return jsonify({"reported": True})
