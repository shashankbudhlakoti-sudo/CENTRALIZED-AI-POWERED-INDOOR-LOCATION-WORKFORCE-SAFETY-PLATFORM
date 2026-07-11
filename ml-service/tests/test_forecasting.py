from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.models.occupancy_series import ZoneOccupancySeries, OccupancySample
from app.models.forecasting import OccupancyForecastModel


def simulate_zone_occupancy(n_days: int, bucket_minutes: int = 15, seed: int = 42) -> pd.DataFrame:
    """Simulates a realistic airport concourse pattern:
    - Daily rhythm: quiet overnight, busy 6am-9am and 4pm-8pm (commute peaks)
    - Weekly rhythm: quieter on weekends
    - Random noise on top
    """
    rng = np.random.default_rng(seed)
    n_buckets = int(n_days * 24 * 60 / bucket_minutes)
    start = datetime(2026, 1, 1)  # a Thursday

    rows = []
    for i in range(n_buckets):
        ts = start + timedelta(minutes=i * bucket_minutes)
        hour = ts.hour + ts.minute / 60
        is_weekend = ts.weekday() >= 5

        # Two commute-peak humps via sum of gaussians over the day
        daily_pattern = (
            40 * np.exp(-((hour - 7.5) ** 2) / 3)
            + 55 * np.exp(-((hour - 17.5) ** 2) / 4)
            + 8  # baseline
        )
        weekend_factor = 0.4 if is_weekend else 1.0
        noise = rng.normal(0, 3)
        occupancy = max(0, round(daily_pattern * weekend_factor + noise))

        rows.append({"ds": ts, "y": occupancy})

    return pd.DataFrame(rows)


def test_occupancy_series_aggregates_events_into_buckets():
    events = [
        {"employee_id": "e1", "zone_id": "concourse-b", "recorded_at": datetime(2026, 1, 1, 8, 2)},
        {"employee_id": "e2", "zone_id": "concourse-b", "recorded_at": datetime(2026, 1, 1, 8, 5)},
        {"employee_id": "e1", "zone_id": "concourse-b", "recorded_at": datetime(2026, 1, 1, 8, 20)},
        {"employee_id": "e3", "zone_id": "other-zone", "recorded_at": datetime(2026, 1, 1, 8, 5)},
    ]
    series = ZoneOccupancySeries.from_position_events("concourse-b", events, bucket_minutes=15)
    df = series.to_dataframe()

    # First 15-min bucket (8:00-8:15) should have e1 and e2 -> count 2
    assert df.iloc[0]["y"] == 2
    # Second bucket (8:15-8:30) should have just e1 -> count 1
    assert df.iloc[1]["y"] == 1
    # other-zone's event should never appear
    assert len(df) == 2


def test_occupancy_series_rejects_unknown_zone():
    events = [{"employee_id": "e1", "zone_id": "zone-a", "recorded_at": datetime(2026, 1, 1, 8, 0)}]
    with pytest.raises(ValueError, match="No position events"):
        ZoneOccupancySeries.from_position_events("zone-b", events)


def test_rejects_insufficient_history():
    df = simulate_zone_occupancy(n_days=1)  # only ~96 buckets at 15 min
    model = OccupancyForecastModel(zone_id="concourse-b")
    with pytest.raises(ValueError, match="need at least"):
        model.fit_and_validate(df, holdout_periods=96)  # would need 288+ samples


def test_model_learns_daily_peak_pattern():
    """The real test: does the model actually learn that ~7:30am and
    5:30pm are peak hours, not just produce numbers that don't crash?"""
    df = simulate_zone_occupancy(n_days=21)  # 3 weeks of history
    model = OccupancyForecastModel(zone_id="concourse-b")
    report = model.fit_and_validate(df, holdout_periods=96)  # last 24h held out

    # MAE should be small relative to the peak occupancy (~95 people) -
    # a model that learned nothing would have much larger error than one
    # that captured the daily rhythm.
    assert report.mae < 15
    assert report.n_holdout == 96


def test_predicted_peaks_align_with_known_commute_hours():
    df = simulate_zone_occupancy(n_days=21)
    model = OccupancyForecastModel(zone_id="concourse-b")
    model.fit_and_validate(df, holdout_periods=96)

    forecast = model.predict(periods=96, bucket_minutes=15)  # predict next 24h
    forecast["hour"] = forecast["ds"].dt.hour + forecast["ds"].dt.minute / 60

    morning_peak = forecast[(forecast["hour"] >= 7) & (forecast["hour"] <= 8)]["yhat"].mean()
    overnight = forecast[(forecast["hour"] >= 1) & (forecast["hour"] <= 4)]["yhat"].mean()

    # The model should clearly distinguish a commute peak from the dead
    # of night - not just predict a flat average everywhere.
    assert morning_peak > overnight + 15


def test_refuses_to_save_unvalidated_model(tmp_path):
    model = OccupancyForecastModel(zone_id="concourse-b")
    with pytest.raises(RuntimeError, match="unvalidated"):
        model.save(tmp_path / "out")


def test_save_and_load_roundtrip(tmp_path):
    df = simulate_zone_occupancy(n_days=21)
    model = OccupancyForecastModel(zone_id="concourse-b")
    model.fit_and_validate(df, holdout_periods=96)

    out_dir = tmp_path / "out"
    model.save(out_dir)

    loaded = OccupancyForecastModel.load(out_dir)
    forecast = loaded.predict(periods=10, bucket_minutes=15)
    assert len(forecast) == 10
    assert loaded.last_validation.mae == model.last_validation.mae
