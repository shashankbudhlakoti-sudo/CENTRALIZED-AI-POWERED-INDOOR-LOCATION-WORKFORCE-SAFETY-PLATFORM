"""
Multilateration from RSSI readings across 3+ fixed gateways.

Two-step process:
  1. rssi_to_distance() - convert each gateway's RSSI reading into an
     estimated distance using a standard log-distance path-loss model.
     This is an ESTIMATE, not a precise measurement - indoor RF is noisy
     and affected by walls/reflections/orientation. That's exactly why
     the output of this module gets smoothed by a Kalman filter
     (position_filter.py) downstream rather than trusted raw.
  2. trilaterate() - given 3+ known gateway positions and their
     estimated distances to the tag, solve for the tag's (x, y) via
     linear least squares.

Calibration note: MEASURED_POWER_AT_1M and PATH_LOSS_EXPONENT below are
reasonable generic defaults, NOT calibrated to your specific hardware/
building. For real accuracy, measure RSSI at a known 1-meter distance
from one of your actual gateways and set MEASURED_POWER_AT_1M to that
observed value - this single number matters more than anything else
here for real-world accuracy.
"""
from __future__ import annotations

import numpy as np

# TODO: calibrate against your real hardware. Walk exactly 1 meter from
# a gateway with the test phone broadcasting, read the RSSI it reports,
# and set this to that value (typically -50 to -65 dBm for BLE).
MEASURED_POWER_AT_1M = -59.0

# Typical indoor value is 2.0 (free space) to 4.0 (many walls/obstacles).
# Airport terminals with metal structures often sit around 2.5-3.5.
PATH_LOSS_EXPONENT = 2.5


def rssi_to_distance(
    rssi: float,
    measured_power: float = MEASURED_POWER_AT_1M,
    path_loss_exponent: float = PATH_LOSS_EXPONENT,
) -> float:
    """Log-distance path-loss model: distance (m) implied by one RSSI
    reading. Monotonic in rssi (stronger signal -> shorter distance) but
    not linear - small RSSI changes near the gateway imply larger
    distance changes than the same RSSI change far away."""
    return 10 ** ((measured_power - rssi) / (10 * path_loss_exponent))


def trilaterate(
    gateway_positions: dict[str, tuple[float, float]],
    distances: dict[str, float],
) -> tuple[float, float] | None:
    """Solve for (x, y) given 3+ (gateway_position, estimated_distance)
    pairs via linear least squares.

    Returns None if fewer than 3 gateways have both a known position AND
    a distance reading - trilateration is geometrically underdetermined
    with fewer than 3 non-collinear reference points, so we refuse to
    guess rather than return a misleading position.
    """
    usable_ids = [gid for gid in distances if gid in gateway_positions]
    if len(usable_ids) < 3:
        return None

    # Linearize: subtract the last anchor's equation from every other
    # anchor's equation to eliminate the squared terms, leaving a linear
    # system solvable by least squares (works cleanly for exactly 3, and
    # averages out noise gracefully if you ever add a 4th+ gateway).
    ref_id = usable_ids[-1]
    xn, yn = gateway_positions[ref_id]
    dn = distances[ref_id]

    A = []
    b = []
    for gid in usable_ids[:-1]:
        xi, yi = gateway_positions[gid]
        di = distances[gid]
        A.append([2 * (xn - xi), 2 * (yn - yi)])
        b.append(di**2 - dn**2 - xi**2 + xn**2 - yi**2 + yn**2)

    A = np.array(A)
    b = np.array(b)
    solution, *_ = np.linalg.lstsq(A, b, rcond=None)
    return float(solution[0]), float(solution[1])
