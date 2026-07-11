import numpy as np
import pytest

from app.models.position_filter import BadgeKalmanFilter


def test_predict_next_before_any_update_raises():
    f = BadgeKalmanFilter()
    with pytest.raises(RuntimeError, match="before any real measurement"):
        f.predict_next(seconds_ahead=2.0)


def test_predict_next_rejects_negative_time():
    f = BadgeKalmanFilter()
    f.update(5.0, 5.0, t=0.0)
    with pytest.raises(ValueError, match="non-negative"):
        f.predict_next(seconds_ahead=-1.0)


def test_predict_next_zero_seconds_matches_last_known_position():
    f = BadgeKalmanFilter()
    f.update(10.0, 5.0, t=0.0)
    f.update(10.0, 5.0, t=1.0)  # stationary, second reading builds real state

    x, y, conf = f.predict_next(seconds_ahead=0.0)
    assert x == pytest.approx(10.0, abs=0.1)
    assert y == pytest.approx(5.0, abs=0.1)


def test_predict_next_extrapolates_in_direction_of_travel():
    """A badge moving steadily right should be predicted to keep moving
    right - this is the actual 'predict the next coordinate' capability."""
    f = BadgeKalmanFilter(process_noise=0.01, measurement_noise=0.1)
    # Walk steadily in +x direction: 1 meter/second
    for i in range(10):
        f.update(x_meas=float(i), y_meas=0.0, t=float(i))

    x, y, conf = f.predict_next(seconds_ahead=2.0)

    # Last real position was ~(9, 0) at t=9, moving at ~1 m/s in x.
    # 2 seconds ahead should predict roughly (11, 0).
    assert x == pytest.approx(11.0, abs=1.0)
    assert y == pytest.approx(0.0, abs=0.5)


def test_predict_next_does_not_mutate_filter_state():
    """Calling predict_next repeatedly should always extrapolate from the
    same last real measurement, not compound drift on drift - i.e. it must
    be a pure read, not a state-changing operation."""
    f = BadgeKalmanFilter()
    f.update(0.0, 0.0, t=0.0)
    f.update(2.0, 0.0, t=1.0)

    first = f.predict_next(seconds_ahead=5.0)
    second = f.predict_next(seconds_ahead=5.0)

    assert first == second


def test_predict_next_confidence_decreases_further_into_the_future():
    """Predicting 10 seconds ahead should be less confident than
    predicting 1 second ahead - uncertainty grows with extrapolation
    distance, and the returned confidence should reflect that."""
    f = BadgeKalmanFilter()
    f.update(0.0, 0.0, t=0.0)
    f.update(1.0, 0.0, t=1.0)

    _, _, near_confidence = f.predict_next(seconds_ahead=1.0)
    _, _, far_confidence = f.predict_next(seconds_ahead=30.0)

    assert far_confidence < near_confidence


def test_predict_next_stationary_badge_stays_put():
    f = BadgeKalmanFilter(process_noise=0.01)
    for i in range(5):
        f.update(x_meas=3.0, y_meas=7.0, t=float(i))

    x, y, conf = f.predict_next(seconds_ahead=3.0)
    assert x == pytest.approx(3.0, abs=0.3)
    assert y == pytest.approx(7.0, abs=0.3)
