from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.auth import hash_password
from app.coach.gemini import Coach
from app.config import Settings
from app.garmin.client import GarminClient
from app.main import create_app

PASSWORD = "correct horse battery"
HDR = {"X-Requested-With": "benji"}


class FakeGarmin(GarminClient):
    def __init__(self, today: date):
        self.today = today
        self.calls = 0

    def fetch(self, start, end):
        self.calls += 1
        days, acts = {}, []
        cur = start
        i = 0
        while cur <= end:
            days[cur.isoformat()] = {
                "steps": 8000.0 + i, "resting_hr": 50.0, "stress_avg": 30.0,
                "body_battery_high": 80.0, "body_battery_low": 20.0,
                "sleep_hours": 7.5, "deep_sleep_hours": 1.5, "rem_sleep_hours": 1.8,
                "sleep_score": 82.0, "hrv_ms": 55.0, "hrv_status": "BALANCED",
                "training_readiness": 70.0, "training_readiness_level": "HIGH",
            }
            cur += timedelta(days=1)
            i += 1
        acts.append({
            "id": "1", "day": end.isoformat(), "start": end.isoformat() + " 07:00:00", "name": "Morning Run",
            "type": "running", "distance_km": 8.0, "duration_min": 45.0, "avg_hr": 150.0, "max_hr": 172.0,
            "calories": 600.0, "elevation_gain_m": 50.0, "pace_min_per_km": 5.6, "aerobic_training_effect": 3.8,
        })
        return days, acts


class Spy:
    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, model, system, history):
        if self.fail:
            raise RuntimeError("boom with secret-key-123")
        self.calls.append((model, system, history))
        return "Looks good. Train easy today."


@pytest.fixture
def settings(tmp_path):
    return Settings(
        gemini_api_key="fake", session_secret="s" * 48, token_enc_key=Fernet.generate_key().decode(),
        app_password_hash=hash_password(PASSWORD), data_dir=tmp_path / "data", cookie_secure=False,
        tz_name="UTC",
    )


@pytest.fixture
def spy():
    return Spy()


@pytest.fixture
def client(settings, spy):
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    app = create_app(settings, FakeGarmin(today), Coach(settings.gemini_model, spy))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed(client):
    r = client.post("/api/login", json={"password": PASSWORD}, headers=HDR)
    assert r.status_code == 200
    return client
