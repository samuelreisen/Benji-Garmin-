from datetime import date

from app.garmin.normalise import normalise_activity, normalise_day
from app.garmin.summarise import build_snapshot

SLEEP = {"dailySleepDTO": {"sleepTimeSeconds": 27000, "deepSleepSeconds": 5400, "remSleepSeconds": 6300,
                           "sleepScores": {"overall": {"value": 81}}}, "restingHeartRate": 49}
HRV = {"hrvSummary": {"lastNightAvg": 48, "status": "BALANCED"}}
SUMMARY = {"totalSteps": 9000, "restingHeartRate": 51, "averageStressLevel": 28,
           "bodyBatteryHighestValue": 85, "bodyBatteryLowestValue": 15}


def test_normalise_day_extracts_and_converts():
    d = normalise_day(SUMMARY, SLEEP, HRV, [{"score": 72, "level": "HIGH"}])
    assert d["sleep_hours"] == 7.5
    assert d["sleep_score"] == 81
    assert d["hrv_ms"] == 48
    assert d["resting_hr"] == 51
    assert d["training_readiness"] == 72
    assert d["training_readiness_level"] == "HIGH"


def test_normalise_day_missing_data_stays_none_not_zero():
    d = normalise_day(None, None, None, None)
    assert all(v is None for v in d.values())


def test_normalise_activity_computes_pace_and_rejects_junk():
    a = normalise_activity({"activityId": 9, "startTimeLocal": "2026-11-01 06:30:00", "activityName": "Run",
                            "activityType": {"typeKey": "running"}, "distance": 10000, "duration": 3000,
                            "averageHR": 150, "aerobicTrainingEffect": 3.9})
    assert a["day"] == "2026-11-01" and a["distance_km"] == 10.0 and a["pace_min_per_km"] == 5.0
    assert normalise_activity({"activityName": "no id"}) is None


def _days(n, **kw):
    out = {}
    for i in range(n):
        d = date(2026, 11, 5).fromordinal(date(2026, 11, 5).toordinal() - i)
        out[d.isoformat()] = {"hrv_ms": 40.0 if i == 0 else 50.0, "sleep_hours": 7.0, **kw}
    return out


def test_snapshot_averages_and_delta():
    snap = build_snapshot(_days(28), [], date(2026, 11, 5))
    hrv = snap["metrics"]["hrv_ms"]
    assert hrv["latest"] == 40.0
    assert hrv["avg_28d"] == round((40 + 27 * 50) / 28, 1)
    assert hrv["latest_vs_28d_avg_pct"] < 0
    assert snap["days_with_data_in_last_28"] == 28


def test_snapshot_handles_empty_data():
    snap = build_snapshot({}, [], date(2026, 11, 5))
    assert snap["metrics"]["hrv_ms"]["latest"] is None
    assert snap["training"]["last_activity"] is None


def test_training_counts_hard_sessions_and_weekly_average():
    acts = [
        {"id": "1", "day": "2026-11-04", "start": "2026-11-04 07:00:00", "type": "running", "distance_km": 10,
         "duration_min": 50, "aerobic_training_effect": 4.2},
        {"id": "2", "day": "2026-10-20", "start": "2026-10-20 07:00:00", "type": "running", "distance_km": 6,
         "duration_min": 30, "aerobic_training_effect": 2.0},
    ]
    t = build_snapshot({}, acts, date(2026, 11, 5))["training"]
    assert t["last_7_days"]["sessions"] == 1 and t["last_7_days"]["hard_sessions"] == 1
    assert t["weekly_average_of_prior_21_days"]["distance_km"] == 2.0
    assert t["last_activity"]["days_ago"] == 1
