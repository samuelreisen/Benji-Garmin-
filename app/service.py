"""The glue: sync Garmin, build the snapshot, ask the coach. No web code in here."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.coach.gemini import Coach
from app.config import Settings
from app.garmin.client import GarminClient
from app.garmin.summarise import METRICS, build_snapshot
from app.store import Store

DEFAULT_PROFILE_FILE = Path(__file__).resolve().parent.parent / "profile.example.json"


class Profile(BaseModel):
    name: str = Field(default="Benji", max_length=40)
    age: int | None = Field(default=None, ge=10, le=100)
    goals: list[str] = Field(default_factory=list, max_length=10)
    injuries: list[str] = Field(default_factory=list, max_length=10)
    weekly_schedule: str = Field(default="", max_length=500)
    equipment: list[str] = Field(default_factory=list, max_length=15)
    swearing: bool = True

    def model_post_init(self, _ctx: Any) -> None:
        for field in ("goals", "injuries", "equipment"):
            cleaned = [str(x).strip()[:120] for x in getattr(self, field) if str(x).strip()]
            setattr(self, field, cleaned)


class Service:
    def __init__(self, settings: Settings, store: Store, garmin: GarminClient, coach: Coach):
        self.settings = settings
        self.store = store
        self.garmin = garmin
        self.coach = coach
        self.tz = ZoneInfo(settings.tz_name)

    def today(self) -> date:
        return datetime.now(self.tz).date()

    # ---- profile ----
    def get_profile(self) -> dict[str, Any]:
        path = self.settings.profile_path
        source = path if path.exists() else DEFAULT_PROFILE_FILE
        try:
            return Profile(**json.loads(source.read_text())).model_dump()
        except (OSError, ValueError):
            return Profile().model_dump()

    def save_profile(self, profile: Profile) -> dict[str, Any]:
        path = self.settings.profile_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(profile.model_dump(), indent=2))
        return profile.model_dump()

    # ---- garmin ----
    def sync(self) -> dict[str, Any]:
        today = self.today()
        first = self.store.get_meta("last_full_sync") is None
        start = today - timedelta(days=27 if first else 3)
        days, acts = self.garmin.fetch(start, today)
        self.store.save_days(days)
        self.store.save_activities(acts)
        if first:
            self.store.set_meta("last_full_sync", today.isoformat())
        stamp = datetime.now(self.tz).isoformat(timespec="minutes")
        self.store.set_meta("last_sync", stamp)
        return {"synced_days": len(days), "activities": len(acts), "last_sync": stamp}

    def snapshot(self) -> dict[str, Any]:
        today = self.today()
        since = (today - timedelta(days=27)).isoformat()
        snap = build_snapshot(self.store.get_days(since), self.store.get_activities(since), today)
        snap["last_sync"] = self.store.get_meta("last_sync")
        return snap

    def series(self) -> dict[str, list[dict[str, Any]]]:
        """Last 28 days per metric, for the trend charts. Missing days are left out, not zero-filled."""
        today = self.today()
        days = self.store.get_days((today - timedelta(days=27)).isoformat())
        out: dict[str, list[dict[str, Any]]] = {k: [] for k in METRICS}
        for day in sorted(days):
            for key in METRICS:
                v = days[day].get(key)
                if isinstance(v, (int, float)):
                    out[key].append({"day": day, "value": v})
        return out

    # ---- coach ----
    def briefing(self, refresh: bool = False) -> dict[str, Any]:
        day = self.today().isoformat()
        cached = None if refresh else self.store.get_briefing(day)
        if cached:
            return {"day": day, "text": cached, "cached": True}
        text = self.coach.briefing(self.get_profile(), self.snapshot())
        self.store.save_briefing(day, text)
        return {"day": day, "text": text, "cached": False}

    def chat(self, message: str) -> str:
        history = self.store.get_chat(30)
        reply = self.coach.chat(self.get_profile(), self.snapshot(), history, message)
        self.store.add_chat("user", message)
        self.store.add_chat("model", reply)
        return reply
