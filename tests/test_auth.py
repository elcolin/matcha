from tests.conftest import login_user, register_user


def test_register_rejects_weak_password(client):
    response = client.post(
        "/register",
        json={
            "email": "weak@example.com",
            "username": "weakuser",
            "last_name": "Test",
            "first_name": "Weak",
            "password": "sunshine",
        },
    )
    assert response.status_code == 400


def test_register_then_login_requires_verification(client):
    register_response = client.post(
        "/register",
        json={
            "email": "unverified@example.com",
            "username": "unverified",
            "last_name": "Test",
            "first_name": "Unverified",
            "password": "Xk7!qzWvLp9Q",
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/login", json={"username": "unverified", "password": "Xk7!qzWvLp9Q"}
    )
    assert login_response.status_code == 403


def test_full_register_verify_login_logout_flow(client):
    register_user(client, "alice")
    login_user(client, "alice")

    me = client.get("/profile/me")
    assert me.status_code == 200
    assert me.get_json()["username"] == "alice"

    logout = client.post("/logout")
    assert logout.status_code == 200

    me_after_logout = client.get("/profile/me")
    assert me_after_logout.status_code == 401


def test_login_locks_out_after_repeated_failures(client, app):
    register_user(client, "bob")
    app.config["LOGIN_RATE_MAX_FAILS"] = 3

    for _ in range(3):
        response = client.post("/login", json={"username": "bob", "password": "wrong"})
        assert response.status_code == 401

    locked_out = client.post("/login", json={"username": "bob", "password": "wrong"})
    assert locked_out.status_code == 429

    # Even the correct password is rejected while locked out.
    still_locked = client.post(
        "/login", json={"username": "bob", "password": "Xk7!qzWvLp9Q"}
    )
    assert still_locked.status_code == 429


def test_password_reset_flow(client):
    register_user(client, "carol")

    request_reset = client.post("/password-reset/request", json={"email": "carol@example.com"})
    assert request_reset.status_code == 200
    reset_link = request_reset.get_json()["reset_link"]
    token = reset_link.rsplit("/", 1)[-1]

    confirm = client.post(f"/password-reset/confirm/{token}", json={"password": "NewStrongPass9!"})
    assert confirm.status_code == 200

    old_password_login = client.post("/login", json={"username": "carol", "password": "Xk7!qzWvLp9Q"})
    assert old_password_login.status_code == 401

    new_password_login = client.post("/login", json={"username": "carol", "password": "NewStrongPass9!"})
    assert new_password_login.status_code == 200
