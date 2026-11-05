"""Garmin data sources behind one interface so the source is swappable.

GarminConnectClient: unofficial `garminconnect` login (works today, unsupported by Garmin).
GarminOfficialClient: placeholder for Garmin's official OAuth API once keys are approved.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings
from app.garmin.normalise import normalise_activity, normalise_day

log = logging.getLogger("benji.garmin")


class GarminError(Exception):
    """Raised with a message that is safe to show the user (never contains secrets)."""


class GarminClient(ABC):
    @abstractmethod
    def fetch(self, start: date, end: date) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Return (days, activities) already in the normalised shape."""


class GarminOfficialClient(GarminClient):
    """Official Garmin API (OAuth). Needs developer-program approval and keys, so not wired yet."""

    def fetch(self, start: date, end: date):  # noqa: D102
        raise GarminError(
            "The official Garmin API client is not set up yet. It needs approved Garmin developer keys. "
            "Use the garminconnect client for now."
        )


class TokenVault:
    """Garmin session tokens, encrypted at rest with a key from the environment."""

    def __init__(self, path, key: str):
        self.path = path
        self._fernet = Fernet(key.encode()) if key else None

    def load(self) -> str | None:
        if not self._fernet or not self.path.exists():
            return None
        try:
            return self._fernet.decrypt(self.path.read_bytes()).decode()
        except (InvalidToken, OSError):
            return None

    def save(self, token_json: str) -> None:
        if not self._fernet:
            return  # no key configured: refuse to write tokens in plaintext
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._fernet.encrypt(token_json.encode()))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


class GarminConnectClient(GarminClient):
    PAUSE_S = 0.4  # be polite to Garmin

    def __init__(self, settings: Settings):
        self.settings = settings
        self.vault = TokenVault(settings.token_path, settings.token_enc_key)
        self._api = None

    def _login(self):
        from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectTooManyRequestsError

        if self._api is not None:
            return self._api
        tokens = self.vault.load()
        try:
            if tokens:
                api = Garmin()
                api.login(tokens)
            else:
                if not (self.settings.garmin_email and self.settings.garmin_password):
                    raise GarminError("No Garmin login set. Add GARMIN_EMAIL and GARMIN_PASSWORD to .env once.")
                api = Garmin(self.settings.garmin_email, self.settings.garmin_password)
                api.login()
                self.vault.save(api.client.dumps())
        except GarminConnectAuthenticationError:
            raise GarminError("Garmin rejected the login. Check the email and password, or MFA.") from None
        except GarminConnectTooManyRequestsError:
            raise GarminError("Garmin is rate limiting us. Wait a few minutes and sync again.") from None
        self._api = api
        return api

    def _try(self, fn, *args):
        try:
            result = fn(*args)
        except Exception as exc:  # one missing metric must not kill the sync
            log.warning("garmin call %s failed: %s", getattr(fn, "__name__", "?"), type(exc).__name__)
            result = None
        time.sleep(self.PAUSE_S)
        return result

    def fetch(self, start: date, end: date):
        api = self._login()
        days: dict[str, dict[str, Any]] = {}
        cur = start
        while cur <= end:
            d = cur.isoformat()
            days[d] = normalise_day(
                self._try(api.get_user_summary, d),
                self._try(api.get_sleep_data, d),
                self._try(api.get_hrv_data, d),
                self._try(api.get_training_readiness, d),
            )
            cur += timedelta(days=1)
        raw_acts = self._try(api.get_activities_by_date, start.isoformat(), end.isoformat()) or []
        acts = [a for a in (normalise_activity(r) for r in raw_acts) if a]
        try:
            self.vault.save(api.client.dumps())  # persist any refreshed tokens
        except Exception:
            pass
        return days, acts
