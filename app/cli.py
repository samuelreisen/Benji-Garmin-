"""Helpers: python -m app.cli [hash-password | gen-secrets | sync | briefing | serve]"""
from __future__ import annotations

import getpass
import sys

from cryptography.fernet import Fernet

from app.auth import hash_password


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "hash-password":
        pw = getpass.getpass("New app password: ")
        if len(pw) < 10 or pw != getpass.getpass("Again: "):
            print("Passwords must match and be at least 10 characters.")
            return 1
        print("APP_PASSWORD_HASH=" + hash_password(pw))
        return 0
    if cmd == "gen-secrets":
        import secrets

        print("SESSION_SECRET=" + secrets.token_urlsafe(48))
        print("TOKEN_ENC_KEY=" + Fernet.generate_key().decode())
        return 0
    if cmd in ("sync", "briefing"):
        from app.config import load_settings
        from app.garmin.client import GarminConnectClient
        from app.coach.gemini import Coach, gemini_transport
        from app.service import Service
        from app.store import Store

        s = load_settings()
        svc = Service(s, Store(s.db_path), GarminConnectClient(s),
                      Coach(s.gemini_model, gemini_transport(s.gemini_api_key) if s.gemini_api_key else None))
        if cmd == "sync":
            print(svc.sync())
        else:
            print(svc.briefing(refresh=True)["text"])
        return 0
    if cmd == "serve":
        import uvicorn

        uvicorn.run("app.main:serve_app", factory=True, host="127.0.0.1", port=8000)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
