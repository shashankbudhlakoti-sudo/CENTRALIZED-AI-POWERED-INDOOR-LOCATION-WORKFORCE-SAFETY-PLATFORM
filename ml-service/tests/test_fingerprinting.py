import numpy as np
import pytest

from app.models.train_mode import LabeledSample, TrainingWalk
from app.models.fingerprinting import FingerprintModel


BEACONS = {
    "beacon-1": (0.0, 0.0),
    "beacon-2": (20.0, 0.0),
    "beacon-3": (0.0, 20.0),
    "beacon-4": (20.0, 20.0),
}


def simulated_rssi(x: float, y: float, rng: np.random.Generator, noise_std: float = 2.0) -> dict[str, float]:
    """Simple log-distance path loss model + noise, standing in for real
    hardware so tests don't depend on physical beacons."""
    readings = {}
    for beacon_id, (bx, by) in BEACONS.items():
        dist = max(np.hypot(x - bx, y - by), 0.1)
        rssi = -40 - 20 * np.log10(dist) + rng.normal(0, noise_std)
        if dist < 25:  # beacons out of practical range simply aren't heard
            readings[beacon_id] = float(rssi)
    return readings


def build_walk(n_samples: int, rng: np.random.Generator, noise_std: float = 2.0) -> TrainingWalk:
    walk = TrainingWalk(zone_id="test-corridor", beacon_ids=list(BEACONS.keys()))
    for _ in range(n_samples):
        x, y = rng.uniform(0, 20), rng.uniform(0, 20)
        walk.add_sample(
            LabeledSample(
                true_x=x, true_y=y,
                rssi=simulated_rssi(x, y, rng, noise_std),
                timestamp=0.0,
            )
        )
    return walk


def test_rejects_walk_with_too_few_samples():
    rng = np.random.default_rng(1)
    walk = build_walk(5, rng)
    model = FingerprintModel(beacon_ids=list(BEACONS.keys()))
    with pytest.raises(ValueError, match="at least 10"):
        model.fit_and_validate(walk)


def test_achieves_reasonable_accuracy_on_clean_signal():
    rng = np.random.default_rng(2)
    walk = build_walk(200, rng, noise_std=1.5)
    model = FingerprintModel(beacon_ids=list(BEACONS.keys()))
    report = model.fit_and_validate(walk)

    # Spec target is 2-5m accuracy (Section 2) - a clean simulated
    # environment with 4 beacons should comfortably beat that.
    assert report.mean_error_m < 3.0
    assert report.n_holdout > 0
    assert report.n_train + report.n_holdout == 200


def test_accuracy_degrades_gracefully_with_more_noise():
    rng_clean = np.random.default_rng(3)
    rng_noisy = np.random.default_rng(3)  # same seed -> same walk positions
    walk_clean = build_walk(200, rng_clean, noise_std=1.0)
    walk_noisy = build_walk(200, rng_noisy, noise_std=8.0)

    model_clean = FingerprintModel(beacon_ids=list(BEACONS.keys()))
    model_noisy = FingerprintModel(beacon_ids=list(BEACONS.keys()))

    report_clean = model_clean.fit_and_validate(walk_clean)
    report_noisy = model_noisy.fit_and_validate(walk_noisy)

    assert report_noisy.mean_error_m > report_clean.mean_error_m


def test_refuses_to_save_unvalidated_model(tmp_path):
    model = FingerprintModel(beacon_ids=list(BEACONS.keys()))
    with pytest.raises(RuntimeError, match="unvalidated"):
        model.save(tmp_path / "model-out")


def test_save_and_load_roundtrip(tmp_path):
    rng = np.random.default_rng(4)
    walk = build_walk(100, rng)
    model = FingerprintModel(beacon_ids=list(BEACONS.keys()))
    model.fit_and_validate(walk)

    out_dir = tmp_path / "model-out"
    model.save(out_dir)

    loaded = FingerprintModel.load(out_dir)
    x, y = loaded.predict(simulated_rssi(10.0, 10.0, np.random.default_rng(5)))
    assert 0 <= x <= 20 and 0 <= y <= 20
    assert loaded.last_validation.mean_error_m == model.last_validation.mean_error_m


def test_rejects_mismatched_beacon_layout():
    rng = np.random.default_rng(6)
    walk = build_walk(50, rng)
    model = FingerprintModel(beacon_ids=["beacon-1", "beacon-2"])  # wrong layout
    with pytest.raises(ValueError, match="beacon layout"):
        model.fit_and_validate(walk)
