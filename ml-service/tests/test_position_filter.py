import numpy as np
import pytest

from app.models.position_filter import BadgeKalmanFilter, PositionFilterRegistry


def test_first_reading_passes_through():
    f = BadgeKalmanFilter()
    x, y, accuracy_m = f.update(10.0, 5.0, t=0.0)
    assert x == 10.0 and y == 5.0
    assert accuracy_m >= 0  # meters-based error estimate, not a 0-1 score


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
