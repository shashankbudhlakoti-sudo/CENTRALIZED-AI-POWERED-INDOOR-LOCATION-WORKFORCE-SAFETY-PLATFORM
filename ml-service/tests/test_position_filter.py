import numpy as np
import pytest

from app.models.position_filter import BadgeKalmanFilter, PositionFilterRegistry


def test_first_reading_passes_through():
    f = BadgeKalmanFilter()
    x, y, accuracy_m = f.update(10.0, 5.0, t=0.0)
    assert x == 10.0 and y == 5.0
    # Strengthened: default measurement_noise=1.0, so first-reading
    # accuracy_m should be exactly sqrt(1.0) = 1.0 - a real meters-based
    # figure, not just ">= 0" (which the old buggy 0.5-confidence value
    # would also have passed, silently missing the regression).
    assert accuracy_m == pytest.approx(1.0, abs=1e-6)


def test_smooths_noisy_stationary_badge():
    """A badge standing still with noisy readings should converge to a
    stable estimate close to the true position, with noise reduced."""
    rng = np.random.default_rng(42)
    true_x, true_y = 20.0, 8.0
    f = BadgeKalmanFilter(measurement_noise=1.0)
    estimates = []
    for i in range(50):
        noisy_x = true_x + rng.normal(0, 0.8)
        noisy_y = true_y + rng.normal(0, 0.8)
        x, y, conf = f.update(noisy_x, noisy_y, t=float(i))
        estimates.append((x, y))
    last_10 = estimates[-10:]
    mean_x = sum(p[0] for p in last_10) / 10
    mean_y = sum(p[1] for p in last_10) / 10
    assert abs(mean_x - true_x) < 0.5
    assert abs(mean_y - true_y) < 0.5
    # Filtered estimates should vary less than raw noise (0.8 std)
    std_x = np.std([p[0] for p in last_10])
    assert std_x < 0.8


def test_low_confidence_reading_trusted_less():
    """A low-confidence outlier reading should move the estimate less than
    a high-confidence one."""
    f_high = BadgeKalmanFilter()
    f_low = BadgeKalmanFilter()
    f_high.update(0.0, 0.0, t=0.0)
    f_low.update(0.0, 0.0, t=0.0)
    x_high, _, _ = f_high.update(10.0, 0.0, t=1.0, confidence=1.0)
    x_low, _, _ = f_low.update(10.0, 0.0, t=1.0, confidence=0.1)
    assert x_low < x_high


def test_registry_keeps_separate_state_per_badge():
    registry = PositionFilterRegistry()
    a = registry.get("badge-a")
    b = registry.get("badge-b")
    assert a is not b
    assert registry.get("badge-a") is a


# --- predict_next() ---

def test_predict_next_before_any_update_raises():
    f = BadgeKalmanFilter()
    with pytest.raises(RuntimeError):
        f.predict_next(5.0)


def test_predict_next_rejects_negative_seconds():
    f = BadgeKalmanFilter()
    f.update(0.0, 0.0, t=0.0)
    with pytest.raises(ValueError):
        f.predict_next(-1.0)


def test_predict_next_zero_seconds_matches_last_position():
    f = BadgeKalmanFilter()
    f.update(5.0, 3.0, t=0.0)
    x, y, accuracy_m = f.predict_next(0.0)
    assert x == pytest.approx(5.0, abs=1e-6)
    assert y == pytest.approx(3.0, abs=1e-6)
    assert accuracy_m >= 0


def test_predict_next_extrapolates_along_known_velocity():
    """A badge moving at a steady velocity should have that velocity
    reflected in the prediction, not just repeat its last position."""
    f = BadgeKalmanFilter(process_noise=0.01, measurement_noise=0.1)
    # Feed several readings moving steadily along +x to give the filter a
    # confident velocity estimate before predicting.
    for i in range(10):
        f.update(float(i), 0.0, t=float(i))
    x, y, _ = f.predict_next(5.0)
    # Should have moved forward from the last real position (9.0, 0.0),
    # not stayed put - dead reckoning should carry the estimated velocity.
    assert x > 9.5


def test_predict_next_accuracy_grows_with_time_ahead():
    """Predicting further into the future should report worse (larger)
    accuracy_m - more time means more uncertainty about where the badge
    actually ended up, since nothing new has actually been measured."""
    f = BadgeKalmanFilter()
    f.update(0.0, 0.0, t=0.0)
    _, _, accuracy_near = f.predict_next(1.0)
    _, _, accuracy_far = f.predict_next(60.0)
    assert accuracy_far > accuracy_near


def test_predict_next_does_not_mutate_filter_state():
    """Repeated predict_next calls for the same tag must always
    extrapolate from the same last real measurement - not compound drift
    on drift by treating a previous prediction as if it were real."""
    f = BadgeKalmanFilter()
    f.update(0.0, 0.0, t=0.0)
    first_call = f.predict_next(10.0)
    second_call = f.predict_next(10.0)
    assert first_call == pytest.approx(second_call, abs=1e-9)
