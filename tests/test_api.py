from tests.conftest import HDR


def test_full_flow_sync_snapshot_briefing_chat(authed, spy):
    assert authed.get("/api/me").json() == {"authenticated": True}
    assert authed.get("/api/briefing").status_code == 502  # no data yet: refuses to guess

    r = authed.post("/api/sync", headers=HDR)
    assert r.status_code == 200 and r.json()["synced_days"] == 28

    snap = authed.get("/api/snapshot").json()
    assert snap["metrics"]["hrv_ms"]["latest"] == 55.0
    assert snap["training"]["last_activity"]["name"] == "Morning Run"

    b = authed.get("/api/briefing").json()
    assert b["text"] == "Looks good. Train easy today." and b["cached"] is False
    assert authed.get("/api/briefing").json()["cached"] is True
    assert len(spy.calls) == 1  # cached, no second Gemini call

    assert '"hrv_ms"' in spy.calls[0][1]  # data reached the system prompt

    r = authed.post("/api/chat", json={"message": "Should I train hard?"}, headers=HDR)
    assert r.json()["reply"] == "Looks good. Train easy today."
    assert [m["role"] for m in authed.get("/api/chat").json()["messages"]] == ["user", "model"]
    r = authed.post("/api/chat", json={"message": "and tomorrow?"}, headers=HDR)
    history = spy.calls[-1][2]
    assert [h["content"] for h in history][-1] == "and tomorrow?" and len(history) == 3


def test_second_sync_is_incremental(authed):
    authed.post("/api/sync", headers=HDR)
    assert authed.post("/api/sync", headers=HDR).json()["synced_days"] == 4


def test_chat_validation_and_clear(authed):
    assert authed.post("/api/chat", json={"message": ""}, headers=HDR).status_code == 422
    assert authed.post("/api/chat", json={"message": "x" * 2001}, headers=HDR).status_code == 422
    authed.post("/api/sync", headers=HDR)
    authed.post("/api/chat", json={"message": "hi"}, headers=HDR)
    assert authed.delete("/api/chat", headers=HDR).status_code == 200
    assert authed.get("/api/chat").json()["messages"] == []


def test_chat_rate_limited(authed):
    authed.post("/api/sync", headers=HDR)
    codes = [authed.post("/api/chat", json={"message": "hi"}, headers=HDR).status_code for _ in range(22)]
    assert codes.count(429) == 2


def test_coach_failure_does_not_leak_details(authed, spy):
    authed.post("/api/sync", headers=HDR)
    spy.fail = True
    r = authed.post("/api/chat", json={"message": "hi"}, headers=HDR)
    assert r.status_code == 502 and "secret-key-123" not in r.text


def test_profile_roundtrip_and_validation(authed):
    p = authed.get("/api/profile").json()
    assert p["name"] == "Benji"
    p.update(age=30, goals=["  run  ", ""], injuries=["knee"])
    saved = authed.put("/api/profile", json=p, headers=HDR).json()
    assert saved["goals"] == ["run"] and saved["age"] == 30
    assert authed.put("/api/profile", json={**p, "age": 5}, headers=HDR).status_code == 422
    assert authed.put("/api/profile", json={**p, "name": "x" * 50}, headers=HDR).status_code == 422


def test_trends_series(authed):
    authed.post("/api/sync", headers=HDR)
    t = authed.get("/api/trends").json()
    assert len(t["hrv_ms"]) == 28 and t["hrv_ms"][0]["value"] == 55.0


def test_logout_ends_session(authed):
    authed.post("/api/logout", headers=HDR)
    assert authed.get("/api/snapshot").status_code == 401


def test_static_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Benji Coach" in r.text
