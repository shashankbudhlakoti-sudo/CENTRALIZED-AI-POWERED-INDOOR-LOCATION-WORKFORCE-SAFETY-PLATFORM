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
        """Feed one raw measurement, get back a smoothed (x, y, accuracy_m).

        `confidence` (input, [0, 1]) scales measurement trust - e.g. a reading
        seen by only one beacon should carry lower confidence than one
        triangulated from four beacons. This is purely an internal filter
        input and is NOT the same field as position_events.accuracy_m.

        The returned third value is accuracy_m: the filter's estimated
        positioning error in meters (derived from the covariance trace),
        matching the schema's position_events.accuracy_m column. It is a
        distinct concept from match_confidence on checkpoint_events, which
        is a face-embedding match score populated elsewhere.
        """
        if self.state is None or self.last_t is None:
            self.state = self._init_state(x_meas, y_meas)
            self.last_t = t
            return x_meas, y_meas, self.measurement_noise ** 0.5  # first reading: no smoothing history yet, report raw sensor noise as the error estimate

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

        # accuracy_m: sqrt of the position covariance trace gives an
        # estimated 1-sigma positioning error in meters - the real quantity
        # position_events.accuracy_m expects, not a bounded 0-1 score.
        position_uncertainty = np.trace(P_new[:2, :2])
        accuracy_m = float(np.sqrt(max(position_uncertainty, 0.0)))

        return float(x_new[0]), float(x_new[1]), accuracy_m

    def predict_next(self, seconds_ahead: float) -> tuple[float, float, float]:
        """Predicts where this badge will be `seconds_ahead` seconds from
        its last known update, WITHOUT a new measurement - pure
        dead-reckoning from the current position and estimated velocity.

        This is for bridging brief signal gaps (a badge walking behind a
        pillar, a beacon dropping one reading) - not a substitute for a
        real reading once one is available, and not the same thing as
        the Prophet occupancy forecaster (forecasting.py), which predicts
        zone-level crowd counts over time, not individual coordinates.

        accuracy_m returned here should generally be treated as worse
        (larger) than a real update()'s accuracy_m, since it's pure
        extrapolation - this is reflected by NOT updating the filter's
        actual state, so repeated calls always extrapolate from the same
        last real measurement rather than compounding drift on drift.

        Raises RuntimeError if called before any real measurement has
        ever been fed in - there is nothing to extrapolate from yet.
        """
        if self.state is None:
            raise RuntimeError(
                "predict_next() called before any real measurement - "
                "call update() at least once first"
            )
        if seconds_ahead < 0:
            raise ValueError("seconds_ahead must be non-negative")

        F = np.array([
            [1, 0, seconds_ahead, 0],
            [0, 1, 0, seconds_ahead],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        Q = np.eye(4) * self.process_noise * seconds_ahead

        x_pred = F @ self.state.x
        P_pred = F @ self.state.P @ F.T + Q

        # Same accuracy_m convention as update() - real meters-based error
        # (sqrt of covariance trace), not a clipped 0-1 confidence score.
        # Extrapolating further ahead should widen this (more time = more
        # uncertainty about where the badge actually ended up).
        position_uncertainty = np.trace(P_pred[:2, :2])
        accuracy_m = float(np.sqrt(max(position_uncertainty, 0.0)))

        return float(x_pred[0]), float(x_pred[1]), accuracy_m


class PositionFilterRegistry:
    """Keeps one BadgeKalmanFilter per tag_id, creating one on first use."""

    def __init__(self):
        self._filters: dict[str, BadgeKalmanFilter] = {}

    def get(self, tag_id: str) -> BadgeKalmanFilter:
        if tag_id not in self._filters:
            self._filters[tag_id] = BadgeKalmanFilter()
        return self._filters[tag_id]
