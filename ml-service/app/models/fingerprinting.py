"""
Fingerprinting model (Section 4.2, row 2 / Section 5).

k-NN baseline first, as specified - simple, hard to get subtly wrong, and a
sensible floor to beat before reaching for a neural net. Learns the
building-specific mapping from an RSSI vector to true position, which beats
pure trilateration math once walls/interference are involved.

Every trained model is validated against a held-out slice of the same walk
BEFORE it is allowed to be saved/deployed - this file will refuse to persist
an unvalidated model, so "the model works" can never be an unverified claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.neighbors import KNeighborsRegressor

from app.models.train_mode import TrainingWalk, train_holdout_split


@dataclass
class ValidationReport:
    n_train: int
    n_holdout: int
    mean_error_m: float
    p90_error_m: float
    max_error_m: float

    def as_dict(self) -> dict:
        """Full precision - used for persistence (meta.json) so a
        reloaded model's reported accuracy is byte-identical to what was
        actually validated, not a rounded approximation of it."""
        return {
            "n_train": self.n_train,
            "n_holdout": self.n_holdout,
            "mean_error_m": self.mean_error_m,
            "p90_error_m": self.p90_error_m,
            "max_error_m": self.max_error_m,
        }

    def as_display_dict(self) -> dict:
        """Rounded - used only for logs/UI, never for persistence."""
        d = self.as_dict()
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}


class FingerprintModel:
    def __init__(self, beacon_ids: list[str], k: int = 5):
        self.beacon_ids = beacon_ids
        self.k = k
        self._model = KNeighborsRegressor(n_neighbors=k, weights="distance")
        self._fitted = False
        self.last_validation: ValidationReport | None = None

    def fit_and_validate(self, walk: TrainingWalk, holdout_fraction: float = 0.2) -> ValidationReport:
        if walk.beacon_ids != self.beacon_ids:
            raise ValueError("Walk's beacon layout does not match this model's expected beacon_ids")

        X, y = walk.to_feature_matrix()
        if len(X) < 10:
            raise ValueError(
                f"Only {len(X)} labeled samples collected - need at least 10 to "
                "get a meaningful holdout validation. Walk the pilot zone again "
                "capturing more reference points (Section 5, steps 1-2)."
            )

        X_train, y_train, X_holdout, y_holdout = train_holdout_split(X, y, holdout_fraction)

        self._model.fit(X_train, y_train)
        self._fitted = True

        preds = self._model.predict(X_holdout)
        errors = np.linalg.norm(preds - y_holdout, axis=1)

        report = ValidationReport(
            n_train=len(X_train),
            n_holdout=len(X_holdout),
            mean_error_m=float(np.mean(errors)),
            p90_error_m=float(np.percentile(errors, 90)),
            max_error_m=float(np.max(errors)),
        )
        self.last_validation = report
        return report

    def predict(self, rssi: dict[str, float], missing_rssi_fill: float = -100.0) -> tuple[float, float]:
        if not self._fitted:
            raise RuntimeError("Model has not been trained yet - call fit_and_validate first")
        x = np.full((1, len(self.beacon_ids)), missing_rssi_fill)
        for beacon_id, val in rssi.items():
            if beacon_id in self.beacon_ids:
                x[0, self.beacon_ids.index(beacon_id)] = val
        pred = self._model.predict(x)[0]
        return float(pred[0]), float(pred[1])

    def save(self, dir_path: Path) -> None:
        """Refuses to save a model that hasn't passed validation - an
        untested model must never silently become "the deployed model"."""
        if not self._fitted or self.last_validation is None:
            raise RuntimeError("Refusing to save an unvalidated model")
        dir_path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, dir_path / "model.joblib")
        (dir_path / "meta.json").write_text(
            json.dumps(
                {
                    "beacon_ids": self.beacon_ids,
                    "k": self.k,
                    "validation": self.last_validation.as_dict(),
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, dir_path: Path) -> "FingerprintModel":
        meta = json.loads((dir_path / "meta.json").read_text())
        instance = cls(beacon_ids=meta["beacon_ids"], k=meta["k"])
        instance._model = joblib.load(dir_path / "model.joblib")
        instance._fitted = True
        instance.last_validation = ValidationReport(**{
            **meta["validation"],
        })
        return instance
