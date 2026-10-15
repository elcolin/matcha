import json
import os
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db import execute, query_all, query_one
from app.utils import is_blocked_between, is_match

"""
Usage:
    python scripts/generate_chat.py [count]             # Seed conversations for up to `count`
                                                          # matched pairs without a chat yet
                                                          # (default: all such pairs)
    python scripts/generate_chat.py cleanup START END   # Delete messages involving users
                                                          # with id between START and END
    python scripts/generate_chat.py cleanall            # Delete all messages

Requires a local Ollama server (https://ollama.com) running with a small instruct model
pulled, e.g.:
    ollama pull qwen2.5:3b-instruct
    ollama serve

The model and host can be overridden with the OLLAMA_MODEL / OLLAMA_HOST env vars.
"""

MODELS = [
    "qwen2.5:3b-instruct",
    "qwen2.5:0.5b",
    "llama3.2:1b",
]
DEFAULT_MODEL = MODELS[0]
MODEL = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_GENERATE_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_TIMEOUT_SECONDS = 30

MAX_GENERATION_ATTEMPTS = 3
MIN_MESSAGES_PER_CONVERSATION = 4
MAX_MESSAGES_PER_CONVERSATION = 10
MIN_GAP_MINUTES = 1
MAX_GAP_MINUTES = 180

MIN_WORDS = 1
MAX_WORDS = 40
MAX_CHARS = 300

BAD_START = [
    "sure",
    "here's",
    "here is",
    "as an ai",
    "i can",
    "of course",
    "bien sûr",
    "voici",
    "en tant qu'ia",
    "je suis une ia",
    "je suis un assistant",
]

FORBIDDEN = [
    "chatbot",
    "language model",
    "modèle de langage",
    "assistant virtuel",
    "assistant ia",
    "intelligence artificielle",
    "en tant qu'ia",
]


class OllamaUnavailableError(RuntimeError):
    pass


def is_valid_message(text):
    if not text:
        return False

    text = text.strip()
    if not text:
        return False

    words = text.split()
    text_lower = text.lower()

    return (
        MIN_WORDS <= len(words) <= MAX_WORDS
        and len(text) <= MAX_CHARS
        and "[" not in text
        and "]" not in text
        and not any(text_lower.startswith(start) for start in BAD_START)
        and not any(word in text_lower for word in FORBIDDEN)
    )


def clean_generated_text(raw, label=None):
    text = raw.strip()
    if label and text.startswith(f"{label}:"):
        text = text[len(label) + 1 :].strip()
    if text:
        text = text.splitlines()[0].strip()
    return text.strip().strip('"').strip("'")


def stagger_timestamps(start, count, min_gap_minutes=MIN_GAP_MINUTES, max_gap_minutes=MAX_GAP_MINUTES):
    """Return `count` strictly increasing datetimes, each a random gap after the previous one."""
    timestamps = []
    current = start
    for _ in range(count):
        current = current + timedelta(minutes=random.randint(min_gap_minutes, max_gap_minutes))
        timestamps.append(current)
    return timestamps


def _ollama_request(url, payload=None, timeout=OLLAMA_TIMEOUT_SECONDS):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise OllamaUnavailableError(
            "Could not reach Ollama at "
            f"{OLLAMA_HOST}. Install it from https://ollama.com, start it with "
            f"`ollama serve`, then pull a model with `ollama pull {MODEL}`."
        ) from exc


def check_ollama_available(model=MODEL):
    body = _ollama_request(OLLAMA_TAGS_URL, payload=None)
    available = {m.get("name") for m in body.get("models", [])}
    if not any(name == model or name.startswith(f"{model}:") or name.split(":")[0] == model.split(":")[0]
               for name in available):
        raise OllamaUnavailableError(
            f"Model '{model}' is not pulled in Ollama. Run `ollama pull {model}` and retry."
        )


def call_ollama(prompt, model=MODEL):
    body = _ollama_request(
        OLLAMA_GENERATE_URL,
        payload={"model": model, "prompt": prompt, "stream": False},
    )
    return body.get("response", "")


def build_prompt(history, next_label):
    transcript = "\n".join(f"{label}: {text}" for label, text in history)
    intro = (
        "You are simulating a private conversation between two people who just matched on a dating app."
    )
    if transcript:
        return f"{intro}\n\n{transcript}\n{next_label}:"
    return f"{intro}\n\n{next_label}:"


def find_candidate_pairs():
    """Distinct (a, b) with a < b for which at least one like row exists between them."""
    rows = query_all("SELECT DISTINCT from_user_id, to_user_id FROM likes")
    pairs = set()
    for row in rows:
        a, b = row["from_user_id"], row["to_user_id"]
        pairs.add((min(a, b), max(a, b)))
    return pairs


def has_existing_messages(user_a, user_b):
    row = query_one(
        """
        SELECT 1 FROM messages
        WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
        LIMIT 1
        """,
        (user_a, user_b, user_b, user_a),
    )
    return bool(row)


def find_matched_pairs(skip_existing=True):
    """Matched (mutually liked), non-blocked pairs, verified via app.utils.is_match."""
    matched = []
    for user_a, user_b in find_candidate_pairs():
        if not is_match(user_a, user_b):
            continue
        if is_blocked_between(user_a, user_b):
            continue
        if skip_existing and has_existing_messages(user_a, user_b):
            continue
        matched.append((user_a, user_b))
    return matched


def conversation_start_time(user_a, user_b):
    row = query_one(
        "SELECT MAX(created_at) AS created_at FROM users WHERE id IN (?, ?)",
        (user_a, user_b),
    )
    earliest = None
    if row and row["created_at"]:
        try:
            earliest = datetime.fromisoformat(row["created_at"])
        except ValueError:
            earliest = None

    lower_bound = earliest or (datetime.now() - timedelta(days=30))
    latest = datetime.now() - timedelta(minutes=random.randint(5, 60))
    if lower_bound >= latest:
        return latest

    delta_seconds = int((latest - lower_bound).total_seconds())
    return lower_bound + timedelta(seconds=random.randint(0, delta_seconds))


def generate_conversation(user_a, user_b, model=MODEL):
    count = random.randint(MIN_MESSAGES_PER_CONVERSATION, MAX_MESSAGES_PER_CONVERSATION)
    current_sender, other = random.sample([user_a, user_b], 2)
    history = []
    messages = []

    for _ in range(count):
        label = "A" if current_sender == user_a else "B"
        prompt = build_prompt(history, label)
        text = None
        for _attempt in range(MAX_GENERATION_ATTEMPTS):
            raw = call_ollama(prompt, model=model)
            candidate = clean_generated_text(raw, label=label)
            if is_valid_message(candidate):
                text = candidate
                break

        if text is None:
            continue

        messages.append((current_sender, other, text))
        history.append((label, text))
        current_sender, other = other, current_sender

    return messages


def insert_conversation(messages, start_time):
    for (sender_id, receiver_id, content), created_at in zip(
        messages, stagger_timestamps(start_time, len(messages))
    ):
        execute(
            "INSERT INTO messages (sender_id, receiver_id, content, created_at) VALUES (?, ?, ?, ?)",
            (sender_id, receiver_id, content, created_at.isoformat(sep=" ")),
        )


def main(count=None, model=MODEL):
    check_ollama_available(model=model)

    pairs = find_matched_pairs()
    if not pairs:
        print("No matched pairs without an existing conversation were found.")
        return 0

    if count is not None:
        pairs = pairs[:count]

    seeded = 0
    for user_a, user_b in pairs:
        messages = generate_conversation(user_a, user_b, model=model)
        if not messages:
            print(f"Skipped pair ({user_a}, {user_b}): no valid message could be generated.")
            continue

        insert_conversation(messages, conversation_start_time(user_a, user_b))
        seeded += 1
        print(f"Seeded {len(messages)} messages between users {user_a} and {user_b}.")

    print(f"Seeded conversations for {seeded} matched pair(s).")
    return seeded


def reset_sequence(table_name):
    execute("DELETE FROM sqlite_sequence WHERE name = ?", (table_name,))


def cleanup(start_id, end_id):
    execute(
        "DELETE FROM messages WHERE sender_id BETWEEN ? AND ? OR receiver_id BETWEEN ? AND ?",
        (start_id, end_id, start_id, end_id),
    )
    reset_sequence("messages")
    print(f"Deleted messages involving users {start_id} to {end_id}.")


def clean_all():
    execute("DELETE FROM messages")
    reset_sequence("messages")
    print("Deleted all seeded messages")


if __name__ == "__main__":
    from app import create_app

    app = create_app()
    with app.app_context():
        if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
            start = int(sys.argv[2]) if len(sys.argv) > 2 else 1
            end = int(sys.argv[3]) if len(sys.argv) > 3 else 500
            cleanup(start, end)
        elif len(sys.argv) > 1 and sys.argv[1] == "cleanall":
            clean_all()
        else:
            arg_count = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
            try:
                main(count=arg_count)
            except OllamaUnavailableError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                sys.exit(1)
