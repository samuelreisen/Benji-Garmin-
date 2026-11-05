"""Turn Garmin's messy per-endpoint JSON into one flat, stable shape. Pure functions, easy to test."""
from __future__ import annotations

from typing import Any


def dig(obj: Any, *path: Any, default: Any = None) -> Any:
    """Safe nested lookup: dig(d, 'a', 'b', 0) never raises."""
    cur = obj
    for key in path:
        try:
            cur = cur[key]
        except (KeyError, IndexError, TypeError):
            return default
        if cur is None:
            return default
    return cur


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _round(value: float | None, places: int = 1) -> float | None:
    return None if value is None else round(value, places)


def normalise_day(
    summary: dict[str, Any] | None,
    sleep: dict[str, Any] | None,
    hrv: dict[str, Any] | None,
    readiness: list[dict[str, Any]] | dict[str, Any] | None,
) -> dict[str, Any]:
    """Flat metrics for one day. Anything Garmin did not return stays None, never guessed."""
    sleep_s = _num(dig(sleep, "dailySleepDTO", "sleepTimeSeconds"))
    deep_s = _num(dig(sleep, "dailySleepDTO", "deepSleepSeconds"))
    rem_s = _num(dig(sleep, "dailySleepDTO", "remSleepSeconds"))
    ready = readiness[0] if isinstance(readiness, list) and readiness else readiness
    return {
        "steps": _num(dig(summary, "totalSteps")),
        "resting_hr": _num(dig(summary, "restingHeartRate")) or _num(dig(sleep, "restingHeartRate")),
        "stress_avg": _num(dig(summary, "averageStressLevel")),
        "body_battery_high": _num(dig(summary, "bodyBatteryHighestValue")),
        "body_battery_low": _num(dig(summary, "bodyBatteryLowestValue")),
        "sleep_hours": _round(sleep_s / 3600 if sleep_s else None, 2),
        "deep_sleep_hours": _round(deep_s / 3600 if deep_s else None, 2),
        "rem_sleep_hours": _round(rem_s / 3600 if rem_s else None, 2),
        "sleep_score": _num(dig(sleep, "dailySleepDTO", "sleepScores", "overall", "value")),
        "hrv_ms": _num(dig(hrv, "hrvSummary", "lastNightAvg")),
        "hrv_status": dig(hrv, "hrvSummary", "status"),
        "training_readiness": _num(dig(ready, "score")),
        "training_readiness_level": dig(ready, "level"),
    }


def normalise_activity(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Flat activity. Returns None if it has no id or start time."""
    act_id = raw.get("activityId")
    start = str(raw.get("startTimeLocal") or "")
    if act_id is None or len(start) < 10:
        return None
    distance_m = _num(raw.get("distance"))
    duration_s = _num(raw.get("duration"))
    km = distance_m / 1000 if distance_m else None
    pace = (duration_s / 60) / km if km and duration_s else None
    return {
        "id": str(act_id),
        "day": start[:10],
        "start": start,
        "name": str(raw.get("activityName") or "")[:80],
        "type": dig(raw, "activityType", "typeKey", default="other"),
        "distance_km": _round(km, 2),
        "duration_min": _round(duration_s / 60 if duration_s else None, 1),
        "avg_hr": _num(raw.get("averageHR")),
        "max_hr": _num(raw.get("maxHR")),
        "calories": _num(raw.get("calories")),
        "elevation_gain_m": _num(raw.get("elevationGain")),
        "pace_min_per_km": _round(pace, 2),
        "aerobic_training_effect": _num(raw.get("aerobicTrainingEffect")),
    }
