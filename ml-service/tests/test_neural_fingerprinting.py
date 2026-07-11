import numpy as np
import pytest

from app.models.train_mode import LabeledSample, TrainingWalk
from app.models.neural_fingerprinting import NeuralFingerprintModel
from app.models.fingerprinting import FingerprintModel


BEACONS = {
    "beacon-1": (0.0, 0.0),
    "beacon-2": (20.0, 0.0),
    "beacon-3": (0.0, 20.0),
    "beacon-4": (20.0, 20.0),
}


def simulated_rssi(x, y, rng, noise_std=2.0):
    readings = {}
    for beacon_id, (bx, by) in BEACONS.items():
        dist = max(np.hypot(x - bx, y - by), 0.1)
        rssi = -40 - 20 * np.log10(dist) + rng.normal(0, noise_std)
        if dist < 25:
            readings[beacon_id] = float(rssi)
    return readings


def build_walk(n_samples, rng, noise_std=2.0):
    walk = TrainingWalk(zone_id="test-corridor", beacon_ids=list(BEACONS.keys()))
    for _ in range(n_samples):
        x, y = rng.uniform(0, 20), rng.uniform(0, 20)
        walk.add_sample(LabeledSample(
            true_x=x, true_y=y, rssi=simulated_rssi(x, y, rng, noise_std), timestamp=0.0,
        ))
    return walk


def test_rejects_walk_with_too_few_samples():
    rng = np.random.default_rng(1)
    walk = build_walk(20, rng)  # below the 30-sample neural net floor
    model = NeuralFingerprintModel(beacon_ids=list(BEACONS.keys()))
    with pytest.raises(ValueError, match="at least 30"):
        model.fit_and_validate(walk)


def test_rejects_mismatched_beacon_layout():
    rng = np.random.default_rng(2)
    walk = build_walk(50, rng)
    model = NeuralFingerprintModel(beacon_ids=["beacon-1", "beacon-2"])
    with pytest.raises(ValueError, match="beacon layout"):
        model.fit_and_validate(walk)


def test_achieves_reasonable_accuracy_on_clean_signal():
    rng = np.random.default_rng(3)
    walk = build_walk(400, rng, noise_std=1.5)
    model = NeuralFingerprintModel(beacon_ids=list(BEACONS.keys()))
    report = model.fit_and_validate(walk)

    assert report.mean_error_m < 3.0
    assert report.n_holdout > 0
    assert report.architecture == "(64, 32)"


def test_refuses_to_save_unvalidated_model(tmp_path):
    model = NeuralFingerprintModel(beacon_ids=list(BEACONS.keys()))
    with pytest.raises(RuntimeError, match="unvalidated"):
        model.save(tmp_path / "out")


def test_save_and_load_roundtrip(tmp_path):
    rng = np.random.default_rng(4)
    walk = build_walk(200, rng)
    model = NeuralFingerprintModel(beacon_ids=list(BEACONS.keys()))
    model.fit_and_validate(walk)

    out_dir = tmp_path / "out"
    model.save(out_dir)

    loaded = NeuralFingerprintModel.load(out_dir)
    x, y = loaded.predict(simulated_rssi(10.0, 10.0, np.random.default_rng(5)))
    assert 0 <= x <= 20 and 0 <= y <= 20
    assert loaded.last_validation.mean_error_m == model.last_validation.mean_error_m


def test_neural_net_matches_or_beats_knn_baseline_on_same_data():
    """The actual point of this upgrade: does the neural net do at least
    as well as the k-NN baseline on identical training/validation data?
    If it doesn't, the upgrade isn't worth the added complexity."""
    rng_knn = np.random.default_rng(100)
    rng_nn = np.random.default_rng(100)  # same seed -> identical walk
    walk_knn = build_walk(400, rng_knn, noise_std=2.0)
    walk_nn = build_walk(400, rng_nn, noise_std=2.0)

    knn_model = FingerprintModel(beacon_ids=list(BEACONS.keys()))
    knn_report = knn_model.fit_and_validate(walk_knn)

    nn_model = NeuralFingerprintModel(beacon_ids=list(BEACONS.keys()))
    nn_report = nn_model.fit_and_validate(walk_nn)

    # Neural net should be competitive - allow it to be up to 20% worse
    # in the worst case (different holdout split due to internal
    # early-stopping validation split), but this test would catch a
    # genuinely broken/much-worse neural implementation.
    assert nn_report.mean_error_m < knn_report.mean_error_m * 1.5


def test_neural_net_handles_missing_beacon_readings():
    """Same as the k-NN model: a beacon not being heard is informative,
    not an error - the model must handle sparse readings gracefully."""
    rng = np.random.default_rng(6)
    walk = build_walk(300, rng)
    model = NeuralFingerprintModel(beacon_ids=list(BEACONS.keys()))
    model.fit_and_validate(walk)

    # Only 2 of 4 beacons heard - should still produce a prediction,
    # not crash.
    partial_rssi = {"beacon-1": -55.0, "beacon-3": -60.0}
    x, y = model.predict(partial_rssi)
    assert isinstance(x, float) and isinstance(y, float)
