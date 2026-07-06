"""
Train Mode (Section 5): the defined workflow for collecting real, labeled
RSSI data so the fingerprinting model learns THIS building's radio behavior
(walls, metal structures, interference) rather than relying on pure
trilateration math alone.

A labeled sample = (true position, RSSI vector) collected by walking a known
path with a badge while logging both. This module defines that data shape
and how walks get split into train/holdout for honest validation - the spec
is explicit that accuracy claims must be validated against a held-out
portion of the walk, not assumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np


@dataclass
class LabeledSample:
    """One point along a training walk."""

    true_x: float
    true_y: float
    rssi: dict[str, float]  # beacon_id -> RSSI reading (dBm), missing beacons omitted
    timestamp: float
    badge_orientation: str = "unknown"  # "pocket" | "hand" | "lanyard" | "unknown"


class TrainingWalk:
    """A single labeled walk session (Section 5, steps 1-3)."""

    def __init__(self, zone_id: str, beacon_ids: list[str]):
        self.zone_id = zone_id
        self.beacon_ids = sorted(beacon_ids)  # fixed ordering -> fixed feature vector layout
        self.samples: list[LabeledSample] = []

    def add_sample(self, sample: LabeledSample) -> None:
        unknown = set(sample.rssi.keys()) - set(self.beacon_ids)
        if unknown:
            raise ValueError(f"RSSI reading references unknown beacon(s): {unknown}")
        self.samples.append(sample)

    def to_feature_matrix(self, missing_rssi_fill: float = -100.0) -> tuple[np.ndarray, np.ndarray]:
        """Returns (X, y) where X is [n_samples, n_beacons] RSSI vectors
        (missing beacons filled with a weak-signal sentinel value, since
        "beacon not heard" is itself informative) and y is [n_samples, 2]
        true (x, y) positions."""
        X = np.full((len(self.samples), len(self.beacon_ids)), missing_rssi_fill)
        y = np.zeros((len(self.samples), 2))
        for i, s in enumerate(self.samples):
            for beacon_id, val in s.rssi.items():
                X[i, self.beacon_ids.index(beacon_id)] = val
            y[i] = [s.true_x, s.true_y]
        return X, y

    def save(self, path: Path) -> None:
        payload = {
            "zone_id": self.zone_id,
            "beacon_ids": self.beacon_ids,
            "samples": [asdict(s) for s in self.samples],
        }
        path.write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: Path) -> "TrainingWalk":
        payload = json.loads(path.read_text())
        walk = cls(payload["zone_id"], payload["beacon_ids"])
        walk.samples = [LabeledSample(**s) for s in payload["samples"]]
        return walk


def train_holdout_split(
    X: np.ndarray, y: np.ndarray, holdout_fraction: float = 0.2, seed: int = 7
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Section 5, step 5: validate against a held-out portion of the walked
    path. Shuffled split, not a time-ordered slice, so the holdout isn't
    just "the last 20% of one continuous corridor" (which would be an
    easier or harder test depending on layout, not a representative one)."""
    rng = np.random.default_rng(seed)
    n = len(X)
    idx = rng.permutation(n)
    n_holdout = max(1, int(n * holdout_fraction))
    holdout_idx, train_idx = idx[:n_holdout], idx[n_holdout:]
    return X[train_idx], y[train_idx], X[holdout_idx], y[holdout_idx]
