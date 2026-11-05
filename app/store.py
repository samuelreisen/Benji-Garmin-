"""SQLite cache of Garmin data, briefings and chat history. Parameterised queries only."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS days (day TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS activities (id TEXT PRIMARY KEY, day TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS briefings (day TEXT PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK (role IN ('user','model')),
                content TEXT NOT NULL,
                created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        self._db.commit()

    # ---- Garmin data ----
    def save_days(self, days: dict[str, dict[str, Any]]) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO days(day, data) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET data=excluded.data",
                [(d, json.dumps(v)) for d, v in days.items()],
            )
            self._db.commit()

    def save_activities(self, activities: list[dict[str, Any]]) -> None:
        with self._lock:
            self._db.executemany(
                "INSERT INTO activities(id, day, data) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET day=excluded.day, data=excluded.data",
                [(str(a["id"]), a["day"], json.dumps(a)) for a in activities],
            )
            self._db.commit()

    def get_days(self, since: str) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT day, data FROM days WHERE day >= ? ORDER BY day", (since,)).fetchall()
        return {r["day"]: json.loads(r["data"]) for r in rows}

    def get_activities(self, since: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM activities WHERE day >= ? ORDER BY day DESC", (since,)
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]

    # ---- briefings ----
    def get_briefing(self, day: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT text FROM briefings WHERE day = ?", (day,)).fetchone()
        return row["text"] if row else None

    def save_briefing(self, day: str, text: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO briefings(day, text, created) VALUES (?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET text=excluded.text, created=excluded.created",
                (day, text, time.time()),
            )
            self._db.commit()

    # ---- chat ----
    def add_chat(self, role: str, content: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO chat(role, content, created) VALUES (?, ?, ?)", (role, content, time.time())
            )
            self._db.commit()

    def get_chat(self, limit: int = 40) -> list[dict[str, str]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, content FROM chat ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_chat(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM chat")
            self._db.commit()

    # ---- meta ----
    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._db.commit()
