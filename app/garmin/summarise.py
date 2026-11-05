"""Raw normalised days + activities -> a small trend snapshot for the coach.

Gemini gets this, not raw Garmin JSON. Every number here is computed, so the coach can quote it.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any

METRICS = [
    "sleep_hours",
    "sleep_score",
    "hrv_ms",
    "resting_hr",
    "stress_avg",
    "body_battery_high",
    "steps",
    "training_readiness",
]
HARD_TRAINING_EFFECT = 3.5


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 1) if values else None


def _window(days: dict[str, dict[str, Any]], key: str, start: date, end: date) -> list[float]:
    out = []
    cur = start
    while cur <= end:
        v = days.get(cur.isoformat(), {}).get(key)
        if isinstance(v, (int, float)):
            out.append(float(v))
        cur += timedelta(days=1)
    return out


def _metric(days: dict[str, dict[str, Any]], key: str, today: date) -> dict[str, Any]:
    latest_day, latest = None, None
    for back in range(0, 8):  # latest reading within the last week
        d = (today - timedelta(days=back)).isoformat()
        v = days.get(d, {}).get(key)
        if isinstance(v, (int, float)):
            latest_day, latest = d, float(v)
            break
    a7 = _avg(_window(days, key, today - timedelta(days=6), today))
    a28 = _avg(_window(days, key, today - timedelta(days=27), today))
    delta = None
    if latest is not None and a28 not in (None, 0):
        delta = round((latest - a28) / a28 * 100, 1)
    return {
        "latest": latest,
        "latest_day": latest_day,
        "avg_7d": a7,
        "avg_28d": a28,
        "latest_vs_28d_avg_pct": delta,
    }


def _training(activities: list[dict[str, Any]], today: date) -> dict[str, Any]:
    d7 = (today - timedelta(days=6)).isoformat()
    d28 = (today - timedelta(days=27)).isoformat()
    last7 = [a for a in activities if a["day"] >= d7]
    prior = [a for a in activities if d28 <= a["day"] < d7]

    def totals(items: list[dict[str, Any]]) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for a in items:
            by_type[a.get("type", "other")] = by_type.get(a.get("type", "other"), 0) + 1
        return {
            "sessions": len(items),
            "distance_km": round(sum(a.get("distance_km") or 0 for a in items), 1),
            "duration_min": round(sum(a.get("duration_min") or 0 for a in items)),
            "hard_sessions": sum(1 for a in items if (a.get("aerobic_training_effect") or 0) >= HARD_TRAINING_EFFECT),
            "by_type": by_type,
        }

    weekly_prior = totals(prior)
    for key in ("sessions", "distance_km", "duration_min", "hard_sessions"):
        weekly_prior[key] = round(weekly_prior[key] / 3, 1)  # 21 days = 3 weeks
    weekly_prior.pop("by_type")

    last = None
    if activities:
        a = max(activities, key=lambda x: x["start"])
        last = {k: a.get(k) for k in (
            "day", "name", "type", "distance_km", "duration_min", "avg_hr",
            "pace_min_per_km", "aerobic_training_effect",
        )}
        last["days_ago"] = (today - date.fromisoformat(a["day"])).days
    return {
        "last_7_days": totals(last7),
        "weekly_average_of_prior_21_days": weekly_prior,
        "last_activity": last,
        "recent_activities": [
            {k: a.get(k) for k in ("day", "name", "type", "distance_km", "duration_min", "avg_hr")}
            for a in sorted(activities, key=lambda x: x["start"], reverse=True)[:8]
        ],
    }


def build_snapshot(
    days: dict[str, dict[str, Any]], activities: list[dict[str, Any]], today: date
) -> dict[str, Any]:
    window_start = (today - timedelta(days=27)).isoformat()
    in_window = {d: v for d, v in days.items() if window_start <= d <= today.isoformat()}
    with_data = [d for d, v in in_window.items() if any(isinstance(x, (int, float)) for x in v.values())]
    last_night = days.get(today.isoformat(), {})
    return {
        "as_of": today.isoformat(),
        "days_with_data_in_last_28": len(with_data),
        "metrics": {key: _metric(days, key, today) for key in METRICS},
        "hrv_status": last_night.get("hrv_status"),
        "training_readiness_level": last_night.get("training_readiness_level"),
        "training": _training(activities, today),
    }
