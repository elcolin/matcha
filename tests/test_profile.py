from tests.conftest import give_profile_photo, login_user, register_user


def test_profile_update_persists_fields_and_tags(client):
    register_user(client, "dave")
    login_user(client, "dave")

    response = client.put(
        "/profile/me",
        json={
            "gender": "male",
            "sexual_preference": "bisexual",
            "bio": "Hello there",
            "city": "Paris",
            "age": 30,
            "tags": ["Vegan", "geek", "vegan"],
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["bio"] == "Hello there"
    assert body["city"] == "Paris"
    assert sorted(body["tags"]) == ["geek", "vegan"]


def test_profile_update_rejects_invalid_gender_and_preference(client):
    register_user(client, "erin")
    login_user(client, "erin")

    response = client.put("/profile/me", json={"gender": "not-a-real-gender"})
    assert response.status_code == 400

    response = client.put("/profile/me", json={"sexual_preference": "nope"})
    assert response.status_code == 400


def test_gps_consent_refused_requires_manual_location(client):
    register_user(client, "frank")
    login_user(client, "frank")

    response = client.put("/profile/me", json={"location_consent_gps": False})
    assert response.status_code == 400


def test_like_requires_a_profile_photo(client, app):
    register_user(client, "gina")
    register_user(client, "hank")
    hank_id = give_profile_photo(app, "hank")

    login_user(client, "gina")
    response = client.post(f"/profile/{hank_id}/like", json={})
    assert response.status_code == 400
    assert "profile photo" in response.get_json()["error"]


def test_mutual_like_creates_a_match(client, app):
    register_user(client, "ivy")
    register_user(client, "jack")
    ivy_id = give_profile_photo(app, "ivy")
    jack_id = give_profile_photo(app, "jack")

    login_user(client, "ivy")
    response = client.post(f"/profile/{jack_id}/like", json={})
    assert response.status_code == 200
    assert response.get_json()["connected"] is False
    client.post("/logout")

    login_user(client, "jack")
    response = client.post(f"/profile/{ivy_id}/like", json={})
    assert response.status_code == 200
    assert response.get_json()["connected"] is True


def test_blocked_user_is_excluded_from_interactions(client, app):
    register_user(client, "kim")
    register_user(client, "leo")
    leo_id = give_profile_photo(app, "leo")
    give_profile_photo(app, "kim")

    login_user(client, "kim")
    client.post(f"/profile/{leo_id}/block", json={})

    response = client.post(f"/profile/{leo_id}/like", json={})
    assert response.status_code == 403


def test_viewing_a_profile_is_recorded(client, app):
    register_user(client, "mia")
    register_user(client, "noah")
    noah_id = give_profile_photo(app, "noah")

    login_user(client, "mia")
    client.get(f"/profile/{noah_id}?format=json")

    client.post("/logout")
    login_user(client, "noah")
    viewers = client.get("/profile/me/viewers").get_json()
    assert any(v["username"] == "mia" for v in viewers)
