from tests.conftest import give_profile_photo, login_user, register_user


def _make_match(client, app, user_a, user_b):
    register_user(client, user_a)
    register_user(client, user_b)

    a_id = give_profile_photo(app, user_a)
    b_id = give_profile_photo(app, user_b)

    login_user(client, user_a)
    client.post(f"/profile/{b_id}/like", json={})
    client.post("/logout")

    login_user(client, user_b)
    client.post(f"/profile/{a_id}/like", json={})
    client.post("/logout")

    return a_id, b_id


def test_chat_requires_a_match(client):
    register_user(client, "uma")
    register_user(client, "vince")
    login_user(client, "uma")

    vince_id = client.get("/match").get_json()
    vince_id = next(u["id"] for u in vince_id if u["username"] == "vince")

    response = client.get(f"/chat/{vince_id}")
    assert response.status_code == 403

    response = client.post(f"/chat/{vince_id}/send", json={"content": "hi"})
    assert response.status_code == 403


def test_matched_users_can_exchange_messages(client, app):
    uma_id, vince_id = _make_match(client, app, "wendy", "xavier")

    login_user(client, "wendy")
    sent = client.post(f"/chat/{vince_id}/send", json={"content": "Hello!"})
    assert sent.status_code == 200
    client.post("/logout")

    login_user(client, "xavier")
    history = client.get(f"/chat/{uma_id}").get_json()
    assert any(m["content"] == "Hello!" for m in history)


def test_active_chat_presence_suppresses_new_message_notification(client, app):
    yara_id, zane_id = _make_match(client, app, "yara", "zane")

    login_user(client, "zane")
    client.post(f"/chat/{yara_id}/presence")
    client.post("/logout")

    login_user(client, "yara")
    client.post(f"/chat/{zane_id}/send", json={"content": "are you there?"})
    client.post("/logout")

    login_user(client, "zane")
    notif_types = [n["type"] for n in client.get("/notifications").get_json()]
    assert "new_message" not in notif_types


def test_message_notification_fires_without_active_presence(client, app):
    amy_id, ben_id = _make_match(client, app, "amy", "ben")

    login_user(client, "amy")
    client.post(f"/chat/{ben_id}/send", json={"content": "hello"})
    client.post("/logout")

    login_user(client, "ben")
    notif_types = [n["type"] for n in client.get("/notifications").get_json()]
    assert "new_message" in notif_types
