"""Thin Gemini wrapper. The transport is injectable so tests never hit the network."""
from __future__ import annotations

from typing import Any, Callable

from app.coach.prompt import BRIEFING_REQUEST, build_system_prompt

# (model, system_prompt, history[{"role","content"}]) -> reply text
Transport = Callable[[str, str, list[dict[str, str]]], str]


class CoachError(Exception):
    """Safe-to-show failure from the coach."""


def gemini_transport(api_key: str) -> Transport:
    def send(model: str, system: str, history: list[dict[str, str]]) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        contents = [
            types.Content(role=m["role"], parts=[types.Part(text=m["content"])]) for m in history
        ]
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.7),
        )
        return (resp.text or "").strip()

    return send


class Coach:
    def __init__(self, model: str, transport: Transport | None, max_history: int = 30):
        self.model = model
        self.transport = transport
        self.max_history = max_history

    def _ask(self, profile: dict[str, Any], snapshot: dict[str, Any], history: list[dict[str, str]]) -> str:
        if self.transport is None:
            raise CoachError("No Gemini key set. Add GEMINI_API_KEY to .env.")
        if not any(snapshot["metrics"][k]["latest"] is not None for k in snapshot["metrics"]) and not snapshot["training"]["last_activity"]:
            raise CoachError("No Garmin data yet. Hit Sync now first so the coach has something to work with.")
        system = build_system_prompt(profile, snapshot)
        try:
            text = self.transport(self.model, system, history[-self.max_history :])
        except Exception:
            raise CoachError("The coach couldn't reach Gemini. Try again in a minute.") from None
        if not text:
            raise CoachError("Gemini sent back nothing. Try rephrasing your question.")
        return text

    def briefing(self, profile: dict[str, Any], snapshot: dict[str, Any]) -> str:
        return self._ask(profile, snapshot, [{"role": "user", "content": BRIEFING_REQUEST}])

    def chat(
        self, profile: dict[str, Any], snapshot: dict[str, Any], history: list[dict[str, str]], message: str
    ) -> str:
        return self._ask(profile, snapshot, history + [{"role": "user", "content": message}])
