"""Settings read from environment. Secrets never live in code or the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    garmin_email: str = ""
    garmin_password: str = ""
    app_password_hash: str = ""
    session_secret: str = ""
    token_enc_key: str = ""
    data_dir: Path = field(default_factory=lambda: Path("./data"))
    cookie_secure: bool = True
    briefing_hour: int = 7
    tz_name: str = "Australia/Sydney"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "benji.sqlite3"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "garmin_tokens.enc"

    @property
    def profile_path(self) -> Path:
        return self.data_dir / "profile.json"


def load_settings() -> Settings:
    load_dotenv()
    env = os.environ.get
    return Settings(
        gemini_api_key=env("GEMINI_API_KEY", ""),
        gemini_model=env("GEMINI_MODEL", "gemini-2.5-flash"),
        garmin_email=env("GARMIN_EMAIL", ""),
        garmin_password=env("GARMIN_PASSWORD", ""),
        app_password_hash=env("APP_PASSWORD_HASH", ""),
        session_secret=env("SESSION_SECRET", ""),
        token_enc_key=env("TOKEN_ENC_KEY", ""),
        data_dir=Path(env("BENJI_DATA_DIR", "./data")),
        cookie_secure=env("COOKIE_SECURE", "1") != "0",
        briefing_hour=int(env("BRIEFING_HOUR", "7")),
        tz_name=env("TZ_NAME", "Australia/Sydney"),
    )
