# Matcha

A dating website built for the 42 school **Matcha** project — mandatory part only (no bonus features).
Deliberately compact, beginner-friendly stack: **Flask** (micro-framework, no ORM) + **SQLite** (hand-written SQL) + **Bootstrap 5** (via CDN, no front-end build step).

## Why this stack

- **Flask** is listed by the subject as a valid micro-framework: it gives you a router and Jinja2 templating, but no ORM, no validators, no user-account manager — all of that is hand-written in this project, as required.
- **SQLite** via the standard `sqlite3` module: no database server to install, every query is written by hand in `app/db.py` and the route files.
- **Bootstrap 5** is loaded from a CDN in `app/templates/base.html`: no npm/build pipeline, just plain HTML/CSS/JS — easy to read and easy to tweak.

## Project structure

```
matcha/
├── run.py                     # entry point (flask run / python run.py)
├── requirements.txt           # flask, python-dotenv, watchdog
├── app/
│   ├── __init__.py            # app factory, blueprints, session loading, notification badge
│   ├── config.py              # configuration (secret key, DB path, uploads, token TTLs...)
│   ├── db.py                  # SQLite connection + query_one/query_all/execute helpers
│   ├── schema.sql             # full DB schema (created automatically on startup)
│   ├── security.py            # password hashing, signed tokens, password-strength rules
│   ├── data/english_words.txt # English dictionary used to reject dictionary-word passwords
│   ├── utils.py                # APIError, login_required, popularity score, notifications...
│   ├── routes.py              # home page
│   ├── auth/routes.py         # register, email verification, login, forgot password
│   ├── profile/routes.py      # profile (edit, photos), like/unlike/block/report, notifications
│   ├── match/routes.py        # suggested profiles + advanced search (sort/filter)
│   ├── chat/routes.py         # messaging + real-time stream (Server-Sent Events)
│   ├── users/routes.py        # placeholder users blueprint
│   ├── templates/
│   │   ├── base.html          # shared layout (Bootstrap navbar, flash messages, footer)
│   │   ├── index.html         # home page
│   │   ├── browse.html        # suggested profiles list (sort/filter)
│   │   ├── search.html        # advanced search
│   │   ├── profile.html       # profile view (like, block, report...)
│   │   ├── profile_edit.html  # edit your own profile + photos
│   │   ├── chat.html          # real-time messaging
│   │   ├── notifications.html # notification list
│   │   ├── auth/               # register/login/forgot-password forms
│   │   └── components/        # reusable fragments (profile card)
│   └── static/
│       ├── css/style.css      # a few visual tweaks on top of Bootstrap
│       └── uploads/           # uploaded profile photos (created automatically, gitignored)
└── instance/matcha.db         # SQLite database (created automatically, gitignored)
```

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # create if you want to override defaults, see "Configuration" below
python run.py
```

The app is served at `http://127.0.0.1:5000`. The SQLite database and the upload folder are created automatically on first run — no migration command needed.

## Configuration

All sensitive values are read from environment variables (see `app/config.py`), with sane defaults for local development. Create a `.env` file at the project root to override them:

```
SECRET_KEY=change-me-in-production
DATABASE_PATH=instance/matcha.db
EMAIL_VERIFY_TOKEN_TTL_SECONDS=86400
PASSWORD_RESET_TTL_SECONDS=3600
LOGIN_RATE_WINDOW_MINUTES=15
LOGIN_RATE_MAX_FAILS=6
```

`.env` is gitignored and must never be committed.

> No email service is wired up: to keep things simple, account-verification and password-reset links are shown directly on screen (flash message) right after registering / requesting a reset, instead of being emailed. That's enough to develop and defend the project locally.

## Implemented features (mandatory part of the subject)

- **Registration / login**: email, username, last name, first name, strong password (10+ characters, upper/lowercase, digit, special character, rejects dictionary words — see [Password strength](#password-strength) below). One-time account-verification link. Login with brute-force protection (temporary lockout after repeated failures). One-click logout. Password reset via link.
- **User profile**: gender, sexual preference, bio, reusable interest tags, up to 5 photos (real file upload, one designated profile picture), GPS geolocation with explicit consent or manual city/neighborhood entry if declined. Editable at any time. List of who viewed your profile and who liked you. Popularity ("fame rating") score computed from views, likes and reports.
- **Browsing**: suggested-profiles list filtered by gender/orientation compatibility (bisexual by default if unset), sorted by geographic area, distance, shared tags and popularity; sortable/filterable by age, location, popularity and tags.
- **Advanced search**: by age range, popularity range, city, tags; results sortable/filterable like browsing.
- **Profile view**: like/unlike, "connected" status on mutual like, online status / last-seen time, report as fake account, block (disappears from results, no more notifications or chat possible), visit history recorded automatically.
- **Real-time chat**: messaging between matched (mutually liked) users, new messages pushed via Server-Sent Events (well under the subject's 10s delay requirement).
- **Real-time notifications**: like received, profile viewed, new message, new match, unlike — unread-count badge visible on every page, updated live via Server-Sent Events.
- **Security**: hashed passwords (never stored in plain text), parameterized SQL queries (no SQL injection), Jinja2 auto-escaping (no HTML/JS injection), server-side validation on every form, upload size/extension limits on photos, signed verification/reset tokens with a limited lifetime.

## Out of scope (subject's bonus part, not implemented)

As requested, no bonus feature was built: no third-party OAuth login, no drag-and-drop photo gallery editor, no interactive map, no audio/video chat, no real-life date scheduling.

## Notes for the defense

- The Flask dev server (`python run.py`) is enough for a local demo; a production server (Gunicorn, Nginx...) wasn't set up since it isn't required for evaluation.
- The database needs at least 500 distinct profiles for evaluation: no seed script ships by default — add one if needed (direct inserts via `sqlite3`, or a small Python script using the helpers in `app/db.py`).

## Development log

This section documents, in order, what was built and fixed, and why — useful context if you're picking this project back up later.

### 1. Initial Bootstrap UI build

The backend (auth, profiles, matching, chat, notifications) already existed as a JSON API with almost no real UI — `register`/`login` were inline `render_template_string` forms, and pages like browsing, search, chat and notifications had no template at all. The UI was built on top of the existing API without changing its JSON contract, so anything talking to it over `fetch`/`curl` keeps working:

- Added `base.html` (Bootstrap 5 navbar/footer/flash messages) and extended `index.html`/`profile.html` from it instead of duplicating markup.
- Added the missing templates: `auth/register.html`, `auth/login.html`, `auth/password_reset_request.html`, `auth/password_reset_confirm.html`, `profile_edit.html`, `browse.html`, `search.html`, `chat.html`, `notifications.html`.
- Routes that used to only return JSON now detect a real `<form>` submission (no JSON body) and respond with `flash()` + `redirect()` instead, while the JSON behavior for API clients is untouched.
- Photo upload (`POST /profile/me/photos`) was rewritten from "paste a URL" to a real `multipart/form-data` file upload, validated by extension/size and saved under `app/static/uploads/`.
- Removed `app/profile/data.py`, a dead module of hardcoded fake profiles that nothing imported.

### 2. Fixed a `TypeError` in browsing/search

`GET /match`, `/match/search` and the new `/match/browse-view` / `/match/search-view` pages crashed with `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'`.

Root cause: in `app/match/routes.py`, the "same area" check was `int((viewer.get("city") and ...) or (viewer.get("neighborhood") and ...))`. In Python, `and`/`or` return one of their operands, not necessarily a boolean — when both users have no city/neighborhood set (the default for a freshly created profile), the whole expression evaluates to `None`, and `int(None)` raises. Fixed by wrapping the expression in `bool(...)` instead of `int(...)`.

### 3. Fixed severe chat delays and over-eager notifications

Two separate issues reported after using the chat feature for real:

- **Delays**: `run.py` started the Flask dev server without `threaded=True`. Since the chat page keeps a long-lived SSE connection open (`GET /chat/stream`), and the dev server is single-threaded by default, that one open connection blocked *every other request* (sending a message, loading any page, etc.) for as long as it stayed open. Fixed by passing `threaded=True` to `app.run(...)`. On top of that, the stream's polling loop slept a full 10 seconds between checks; it now polls every 1 second (the unread-count "heartbeat" event is still only emitted roughly every 10s, to avoid hammering the DB for something that doesn't need to be that fresh).
- **Notifications while actively chatting**: a `new_message` notification used to fire every time, even if the recipient already had that exact conversation open. Added a small `chat_presence` table (`user_id`, `partner_id`, `updated_at`) and a `POST /chat/<id>/presence` endpoint that the chat page pings on load and every 8 seconds while a conversation is open. `send_message` now skips creating the `new_message` notification if the recipient's presence ping for that conversation is less than 15 seconds old — the message still appears instantly either way, since it's delivered through the separate `message` SSE event, not through the notifications table.

### 4. Dictionary-based password check

The subject requires that "commonly used dictionary words (regardless of language) should not be accepted as passwords." The original check only compared the password against a hand-typed list of ~100 common passwords (`password`, `qwerty`, etc.) — not an actual dictionary check.

Replaced it with a real English word list: `app/data/english_words.txt` (~210k lowercase words, derived from the system dictionary, bundled in the repo so the check doesn't depend on the OS having `/usr/share/dict/words` installed). `app/security.py` loads it once into a cached `frozenset` and `is_dictionary_word()` checks the password — with any leading/trailing digits and symbols stripped first (so `Summer2025!` is still caught as the word "summer") — against that set. No extra dependency was added; it's just a static text file read at startup.
