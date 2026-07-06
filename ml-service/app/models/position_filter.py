"""
Position filtering (Section 4.2, row 1 of the AI/ML table).

Raw trilaterated positions from RSSI are jumpy - a badge sitting still can
appear to jump half a meter between readings due to radio noise. A Kalman
filter treats each raw reading as a noisy observation of a smoothly moving
object and outputs a stable estimate plus a confidence value.

This is a constant-velocity 2D Kalman filter: state = [x, y, vx, vy].
One instance is kept per active badge (see PositionFilterRegistry).
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class KalmanState:
    x: np.ndarray  # state vector [x, y, vx, vy]
    P: np.ndarray  # state covariance


class BadgeKalmanFilter:
    """Constant-velocity Kalman filter for one badge's 2D position."""

    def __init__(
        self,
        process_noise: float = 0.05,
        measurement_noise: float = 1.0,
    ):
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.state: KalmanState | None = None
        self.last_t: float | None = None

    def _init_state(self, x: float, y: float) -> KalmanState:
        return KalmanState(
            x=np.array([x, y, 0.0, 0.0]),
            P=np.eye(4) * 10.0,
        )

    def update(self, x_meas: float, y_meas: float, t: float, confidence: float = 1.0) -> tuple[float, float, float]:
        """Feed one raw measurement, get back a smoothed (x, y, confidence).

        confidence in [0, 1] scales measurement trust - e.g. a reading seen
        by only one beacon should carry lower confidence than one triangulated
        from four beacons.
        """
        if self.state is None or self.last_t is None:
            self.state = self._init_state(x_meas, y_meas)
            self.last_t = t
            return x_meas, y_meas, 0.5  # first reading: no smoothing history yet

        dt = max(t - self.last_t, 1e-3)
        self.last_t = t

        F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        Q = np.eye(4) * self.process_noise * dt

        # Predict
        x_pred = F @ self.state.x
        P_pred = F @ self.state.P @ F.T + Q

        # Measurement model: we observe x, y directly
        H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ])
        # Lower confidence -> higher measurement noise -> filter trusts the
        # prediction more than this particular noisy reading.
        r = self.measurement_noise / max(confidence, 0.05)
        R = np.eye(2) * r

        z = np.array([x_meas, y_meas])
        y_resid = z - H @ x_pred
        S = H @ P_pred @ H.T + R
        K = P_pred @ H.T @ np.linalg.inv(S)

        x_new = x_pred + K @ y_resid
        P_new = (np.eye(4) - K @ H) @ P_pred

        self.state = KalmanState(x=x_new, P=P_new)

        # Output confidence: shrink with estimate uncertainty (trace of P position block)
        position_uncertainty = np.trace(P_new[:2, :2])
        out_confidence = float(np.clip(1.0 / (1.0 + position_uncertainty), 0.0, 1.0))

        return float(x_new[0]), float(x_new[1]), out_confidence


class PositionFilterRegistry:
    """Keeps one filter instance per badge so state persists across calls.

    In production this process should be the ONLY writer of filtered
    positions - if you scale to multiple ML service replicas, badge->filter
    assignment must be sticky (e.g. consistent hashing on tag_id) or state
    needs to move to Redis. Documented here so this isn't a surprise later.
    """

    def __init__(self):
        self._filters: dict[str, BadgeKalmanFilter] = {}

    def get(self, tag_id: str) -> BadgeKalmanFilter:
        if tag_id not in self._filters:
            self._filters[tag_id] = BadgeKalmanFilter()
        return self._filters[tag_id]
