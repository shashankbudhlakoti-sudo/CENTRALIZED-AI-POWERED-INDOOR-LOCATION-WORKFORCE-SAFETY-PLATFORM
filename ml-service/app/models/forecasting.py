"""
Occupancy forecasting model (Section 4.2, row 6).

Wraps Prophet, but never trusts it blindly: a model is validated against
a genuinely held-out tail of the real series before it's allowed to be
saved/deployed - same principle as the fingerprinting model. A forecast
that hasn't been checked against real held-out data is a guess dressed
up as a prediction, and this file refuses to ship that.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# Prophet checks for optional plotly support at import time and logs a
# warning if it's missing - harmless here since we never call any of
# Prophet's plotting functions (plot_plotly, plot_components_plotly),
# only fit/predict/save/load. Silenced so it doesn't look like a real
# error in production logs.
logging.getLogger("prophet.plot").setLevel(logging.ERROR)

from prophet import Prophet
from prophet.serialize import model_to_json, model_from_json


@dataclass
class ForecastValidationReport:
    n_train: int
    n_holdout: int
    mae: float          # mean absolute error, in people (occupancy count units)
    mape_pct: float      # mean absolute percentage error - meaningful only where actual > 0

    def as_dict(self) -> dict:
        return {
            "n_train": self.n_train,
            "n_holdout": self.n_holdout,
            "mae": self.mae,
            "mape_pct": self.mape_pct,
        }


class OccupancyForecastModel:
    def __init__(self, zone_id: str):
        self.zone_id = zone_id
        self._model: Prophet | None = None
        self.last_validation: ForecastValidationReport | None = None

    def fit_and_validate(self, df: pd.DataFrame, holdout_periods: int) -> ForecastValidationReport:
        """df must have 'ds' and 'y' columns (see ZoneOccupancySeries.to_dataframe).
        holdout_periods = number of trailing buckets held out for validation -
        e.g. 96 buckets at 15-min resolution = last 24 hours withheld from
        training and used purely to check the forecast against reality.
        """
        if len(df) < holdout_periods * 3:
            raise ValueError(
                f"Only {len(df)} samples available, need at least {holdout_periods * 3} "
                f"(3x the holdout window) for a meaningful validation. Collect more "
                f"history before training a forecast for this zone."
            )

        df = df.sort_values("ds").reset_index(drop=True)
        train_df = df.iloc[:-holdout_periods]
        holdout_df = df.iloc[-holdout_periods:]

        model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,  # not enough history to trust this for a pilot
            interval_width=0.8,
        )
        model.fit(train_df)

        future = holdout_df[["ds"]]
        forecast = model.predict(future)

        actual = holdout_df["y"].values
        predicted = forecast["yhat"].values
        errors = np.abs(actual - predicted)

        # MAPE only over buckets with actual occupancy > 0, since percentage
        # error against a true zero is undefined/misleading.
        nonzero_mask = actual > 0
        mape = (
            float(np.mean(errors[nonzero_mask] / actual[nonzero_mask]) * 100)
            if nonzero_mask.any() else float("nan")
        )

        report = ForecastValidationReport(
            n_train=len(train_df),
            n_holdout=len(holdout_df),
            mae=float(np.mean(errors)),
            mape_pct=mape,
        )

        # Refit on the FULL series (train + holdout) for the deployed model,
        # now that we've honestly measured accuracy on the held-out part.
        # This is standard practice: validate on a split, then use all
        # available data for the model that actually gets used.
        self._model = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
            interval_width=0.8,
        )
        self._model.fit(df)
        self.last_validation = report
        return report

    def predict(self, periods: int, bucket_minutes: int) -> pd.DataFrame:
        """Returns a DataFrame with ds, yhat, yhat_lower, yhat_upper for the
        next `periods` buckets beyond the training data."""
        if self._model is None:
            raise RuntimeError("Model has not been trained yet - call fit_and_validate first")
        future = self._model.make_future_dataframe(periods=periods, freq=f"{bucket_minutes}min")
        forecast = self._model.predict(future)
        return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(periods)

    def save(self, dir_path: Path) -> None:
        """Refuses to save an unvalidated model - same rule as the
        fingerprinting model, for the same reason."""
        if self._model is None or self.last_validation is None:
            raise RuntimeError("Refusing to save an unvalidated forecast model")
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / "model.json").write_text(model_to_json(self._model))
        (dir_path / "meta.json").write_text(json.dumps({
            "zone_id": self.zone_id,
            "validation": self.last_validation.as_dict(),
        }, indent=2))

    @classmethod
    def load(cls, dir_path: Path) -> "OccupancyForecastModel":
        meta = json.loads((dir_path / "meta.json").read_text())
        instance = cls(zone_id=meta["zone_id"])
        instance._model = model_from_json((dir_path / "model.json").read_text())
        instance.last_validation = ForecastValidationReport(**meta["validation"])
        return instance
