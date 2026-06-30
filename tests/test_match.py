from tests.conftest import login_user, register_user


def test_browse_view_does_not_crash_when_no_location_is_set(client):
    """Regression test: same_area used to be computed with int(None) and
    raised a TypeError whenever neither user had set a city/neighborhood."""
    register_user(client, "oscar")
    register_user(client, "paula")
    login_user(client, "oscar")

    response = client.get("/match/browse-view")
    assert response.status_code == 200

    response = client.get("/match/search-view")
    assert response.status_code == 200


def test_match_suggestions_exclude_self_and_blocked_users(client):
    register_user(client, "quinn")
    register_user(client, "rosa")
    login_user(client, "quinn")

    quinn_id = client.get("/profile/me").get_json()["id"]
    rosa_id = next(
        u["id"] for u in client.get("/match").get_json() if u["username"] == "rosa"
    )

    assert all(u["id"] != quinn_id for u in client.get("/match").get_json())

    client.post(f"/profile/{rosa_id}/block", json={})
    assert all(u["username"] != "rosa" for u in client.get("/match").get_json())


def test_search_filters_by_age_range(client):
    register_user(client, "sara")
    register_user(client, "tom")
    login_user(client, "sara")
    client.put("/profile/me", json={"age": 25})
    client.post("/logout")

    login_user(client, "tom")
    client.put("/profile/me", json={"age": 50})

    results = client.get("/match/search?min_age=40&max_age=60").get_json()
    assert all(r.get("age", 0) >= 40 for r in results)
    assert any(r["username"] == "sara" for r in results) is False
