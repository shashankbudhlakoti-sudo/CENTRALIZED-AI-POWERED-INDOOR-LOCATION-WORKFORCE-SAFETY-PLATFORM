"""
Fingerprinting model upgrade: k-NN baseline -> neural net (Section 5).

Uses scikit-learn's MLPRegressor rather than PyTorch/TensorFlow. This is a
deliberate choice, not a shortcut: this project already spent real,
painful effort getting InsightFace and Prophet/cmdstan to build correctly
in Docker today. Adding a full deep learning framework as a new dependency
risks repeating that exact class of problem for a model that, for this
scale of data (a handful of beacons, thousands of training points), does
not need it - an MLP already gives us a genuine neural network with
non-linear decision boundaries, without any new native-compilation risk.

Same interface and same non-negotiable rule as the k-NN version
(fingerprinting.py): a model is validated against genuinely held-out data
before it's allowed to be saved/deployed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

from app.models.train_mode import TrainingWalk, train_holdout_split


@dataclass
class NeuralValidationReport:
    n_train: int
    n_holdout: int
    mean_error_m: float
    p90_error_m: float
    max_error_m: float
    architecture: str  # e.g. "(64, 32)" - recorded so a saved model's
    # accuracy claim is tied to the specific architecture that produced it

    def as_dict(self) -> dict:
        return {
            "n_train": self.n_train,
            "n_holdout": self.n_holdout,
            "mean_error_m": self.mean_error_m,
            "p90_error_m": self.p90_error_m,
            "max_error_m": self.max_error_m,
            "architecture": self.architecture,
        }


class NeuralFingerprintModel:
    """Drop-in upgrade path for FingerprintModel (fingerprinting.py) -
    same fit_and_validate/predict/save/load shape, so callers can switch
    between k-NN and neural implementations without changing anything
    else. RSSI inputs are standardized (StandardScaler) before the MLP,
    since neural nets are sensitive to input scale in a way k-NN's
    distance-weighting is not - this is not optional for MLPRegressor to
    train well.
    """

    def __init__(self, beacon_ids: list[str], hidden_layer_sizes: tuple[int, ...] = (64, 32)):
        self.beacon_ids = beacon_ids
        self.hidden_layer_sizes = hidden_layer_sizes
        self._scaler = StandardScaler()
        self._model = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            activation="relu",
            solver="adam",
            max_iter=2000,
            early_stopping=True,
            n_iter_no_change=20,
            random_state=7,  # reproducible training - important for a
            # model whose accuracy claim gets persisted and trusted later
        )
        self._fitted = False
        self.last_validation: NeuralValidationReport | None = None

    def fit_and_validate(self, walk: TrainingWalk, holdout_fraction: float = 0.2) -> NeuralValidationReport:
        if walk.beacon_ids != self.beacon_ids:
            raise ValueError("Walk's beacon layout does not match this model's expected beacon_ids")

        X, y = walk.to_feature_matrix()
        if len(X) < 30:
            # Neural nets need more data than k-NN to learn a useful
            # mapping rather than memorize noise - a stricter floor than
            # the k-NN model's 10-sample minimum, and an honest one.
            raise ValueError(
                f"Only {len(X)} labeled samples collected - a neural net "
                f"needs at least 30 to have any chance of learning a real "
                f"pattern rather than overfitting noise. Walk the pilot "
                f"zone again capturing more reference points, or use the "
                f"k-NN baseline (fingerprinting.py) instead for small datasets."
            )

        X_train, y_train, X_holdout, y_holdout = train_holdout_split(X, y, holdout_fraction)

        X_train_scaled = self._scaler.fit_transform(X_train)
        X_holdout_scaled = self._scaler.transform(X_holdout)

        self._model.fit(X_train_scaled, y_train)
        self._fitted = True

        preds = self._model.predict(X_holdout_scaled)
        errors = np.linalg.norm(preds - y_holdout, axis=1)

        report = NeuralValidationReport(
            n_train=len(X_train),
            n_holdout=len(X_holdout),
            mean_error_m=float(np.mean(errors)),
            p90_error_m=float(np.percentile(errors, 90)),
            max_error_m=float(np.max(errors)),
            architecture=str(self.hidden_layer_sizes),
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
        x_scaled = self._scaler.transform(x)
        pred = self._model.predict(x_scaled)[0]
        return float(pred[0]), float(pred[1])

    def save(self, dir_path: Path) -> None:
        if not self._fitted or self.last_validation is None:
            raise RuntimeError("Refusing to save an unvalidated model")
        dir_path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, dir_path / "model.joblib")
        joblib.dump(self._scaler, dir_path / "scaler.joblib")
        (dir_path / "meta.json").write_text(
            json.dumps(
                {
                    "beacon_ids": self.beacon_ids,
                    "hidden_layer_sizes": list(self.hidden_layer_sizes),
                    "validation": self.last_validation.as_dict(),
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, dir_path: Path) -> "NeuralFingerprintModel":
        meta = json.loads((dir_path / "meta.json").read_text())
        instance = cls(
            beacon_ids=meta["beacon_ids"],
            hidden_layer_sizes=tuple(meta["hidden_layer_sizes"]),
        )
        instance._model = joblib.load(dir_path / "model.joblib")
        instance._scaler = joblib.load(dir_path / "scaler.joblib")
        instance._fitted = True
        instance.last_validation = NeuralValidationReport(**meta["validation"])
        return instance
