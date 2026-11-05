import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.auth import LoginGuard, RateLimiter, hash_password, verify_password
from app.garmin.client import TokenVault
from app.main import create_app
from app.store import Store
from tests.conftest import HDR, PASSWORD, FakeGarmin


def test_password_hashing():
    h = hash_password("hunter2hunter2")
    assert h != "hunter2hunter2" and verify_password("hunter2hunter2", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", "")  # nothing configured means nobody gets in


def test_lockout_after_failures_and_reset():
    t = [0.0]
    g = LoginGuard(max_failures=3, lockout_s=60, clock=lambda: t[0])
    for _ in range(3):
        g.failure("ip")
    assert g.seconds_locked("ip") > 0
    t[0] = 61
    assert g.seconds_locked("ip") == 0


def test_rate_limiter_window():
    t = [0.0]
    r = RateLimiter(2, 10, clock=lambda: t[0])
    assert r.allow("k") and r.allow("k") and not r.allow("k")
    t[0] = 11
    assert r.allow("k")


def test_token_vault_encrypts_at_rest(tmp_path):
    key = Fernet.generate_key().decode()
    v = TokenVault(tmp_path / "t.enc", key)
    v.save('{"refresh_token": "SUPERSECRET"}')
    assert b"SUPERSECRET" not in (tmp_path / "t.enc").read_bytes()
    assert v.load() == '{"refresh_token": "SUPERSECRET"}'
    assert TokenVault(tmp_path / "t.enc", Fernet.generate_key().decode()).load() is None


def test_vault_refuses_plaintext_without_key(tmp_path):
    TokenVault(tmp_path / "t.enc", "").save("secret")
    assert not (tmp_path / "t.enc").exists()


def test_store_is_injection_safe(tmp_path):
    s = Store(tmp_path / "x.sqlite3")
    nasty = "'); DROP TABLE chat;--"
    s.add_chat("user", nasty)
    assert s.get_chat()[0]["content"] == nasty


def test_app_refuses_to_start_without_secret(settings):
    from dataclasses import replace
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app(replace(settings, session_secret=""), FakeGarmin(None))


def test_api_requires_login(client):
    for path in ("/api/snapshot", "/api/briefing", "/api/chat", "/api/profile", "/api/trends"):
        assert client.get(path).status_code == 401
    assert client.post("/api/sync", headers=HDR).status_code == 401


def test_csrf_header_required_on_writes(client):
    assert client.post("/api/login", json={"password": PASSWORD}).status_code == 403


def test_wrong_password_then_lockout(client):
    for _ in range(5):
        assert client.post("/api/login", json={"password": "nope"}, headers=HDR).status_code == 401
    r = client.post("/api/login", json={"password": PASSWORD}, headers=HDR)
    assert r.status_code == 429  # locked even with the right password


def test_security_headers_and_cookie_flags(settings):
    from dataclasses import replace
    app = create_app(replace(settings, cookie_secure=True), FakeGarmin(None))
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/login", json={"password": PASSWORD}, headers=HDR)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY" and "strict-transport-security" in r.headers
    assert r.headers["cache-control"] == "no-store"


def test_no_docs_or_debug_routes(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
