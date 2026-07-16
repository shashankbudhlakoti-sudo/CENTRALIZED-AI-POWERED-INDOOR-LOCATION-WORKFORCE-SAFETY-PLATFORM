"""
Run with: pytest test_trilateration.py -v
(pip install pytest if not already installed: pip install pytest --break-system-packages)
"""
import math

from trilateration import rssi_to_distance, trilaterate, MEASURED_POWER_AT_1M, PATH_LOSS_EXPONENT

GATEWAYS = {
    "gw-north": (0.0, 20.0),
    "gw-south": (0.0, 0.0),
    "gw-east": (20.0, 10.0),
}


def simulate_rssi(true_x: float, true_y: float, gw_x: float, gw_y: float) -> float:
    """Inverse of rssi_to_distance - generates a clean (noise-free) RSSI
    reading for a known true position, so the test can check the round
    trip: true position -> simulated RSSI -> distance -> trilaterated
    position should land back close to the true position."""
    dist = max(math.hypot(true_x - gw_x, true_y - gw_y), 0.1)
    return MEASURED_POWER_AT_1M - 10 * PATH_LOSS_EXPONENT * math.log10(dist)


def test_recovers_known_position_within_tolerance():
    true_x, true_y = 10.0, 8.0

    distances = {
        gid: rssi_to_distance(simulate_rssi(true_x, true_y, gx, gy))
        for gid, (gx, gy) in GATEWAYS.items()
    }

    result = trilaterate(GATEWAYS, distances)
    assert result is not None

    est_x, est_y = result
    error = math.hypot(est_x - true_x, est_y - true_y)
    # Clean/noise-free signal should recover the position almost exactly -
    # a loose tolerance here would hide a real bug in the linear algebra.
    assert error < 0.1, f"error={error:.3f}m, got=({est_x:.2f},{est_y:.2f})"


def test_returns_none_with_fewer_than_three_gateways():
    partial = {"gw-north": 5.0, "gw-south": 6.0}  # only 2
    assert trilaterate(GATEWAYS, partial) is None


def test_returns_none_when_gateway_position_unknown():
    # 3 readings, but one gateway_id isn't in GATEWAYS at all
    unknown = {"gw-north": 5.0, "gw-south": 6.0, "gw-mystery": 7.0}
    assert trilaterate(GATEWAYS, unknown) is None


def test_tolerates_realistic_rssi_noise():
    """Same as the clean-signal test, but with +/-3 dBm of noise added -
    checks the result stays in a sane ballpark, not pinpoint-exact,
    since real hardware never gives clean readings."""
    import random
    random.seed(42)

    true_x, true_y = 10.0, 8.0
    distances = {
        gid: rssi_to_distance(simulate_rssi(true_x, true_y, gx, gy) + random.uniform(-3, 3))
        for gid, (gx, gy) in GATEWAYS.items()
    }

    result = trilaterate(GATEWAYS, distances)
    assert result is not None
    est_x, est_y = result
    error = math.hypot(est_x - true_x, est_y - true_y)
    # +/-3 dBm noise gets amplified non-linearly by the log-distance
    # formula - this is real RF behavior, not a bug, and is exactly why
    # raw trilateration output must be smoothed downstream by the Kalman
    # filter (position_filter.py) rather than trusted directly.
    assert error < 4.5, f"error={error:.3f}m too large even with modest noise"
