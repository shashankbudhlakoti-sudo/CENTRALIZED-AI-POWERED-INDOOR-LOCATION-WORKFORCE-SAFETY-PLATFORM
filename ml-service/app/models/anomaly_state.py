"""
In-memory per-tag state for the real-time anomaly checks hooked into
/internal/filter-position (zone_breach, inactivity). Deliberately pure
and dependency-free - no DB, no network - so this logic is fully testable
before wiring it into the actual endpoint.

LIMITATION, flagged rather than hidden: this state is in-memory only.
- It resets on service restart (a badge already inside a restricted zone
  or already stationary won't re-trigger until it next transitions).
- It is NOT shared across multiple horizontally-scaled instances of this
  service - each instance tracks its own view, which could cause a missed
  transition (if consecutive readings for the same tag land on different
  instances) or a duplicate alert (if an instance restarts mid-episode).
Fine for a single-instance pilot deployment; revisit (e.g. Redis-backed
state) before scaling out to multiple instances.
"""
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZoneBreachState:
    """Tracks whether each tag is currently inside a restricted zone, so
    callers alert on the ENTRY transition only - not on every single
    position reading while someone remains inside (which would otherwise
    fire one alert per reading, often multiple times a second)."""

    _inside_zone: dict = field(default_factory=dict)  # tag_id -> zone_id

    def check_entry(self, tag_id: str, zone_id: Optional[str]) -> bool:
        """Returns True exactly once per entry: when this tag transitions
        from 'not in a restricted zone' (or in a different one) to
        'in restricted zone <zone_id>'. zone_id=None means the tag is
        not currently inside any restricted zone."""
        was_inside = self._inside_zone.get(tag_id)

        if zone_id is None:
            self._inside_zone.pop(tag_id, None)
            return False

        if was_inside == zone_id:
            return False  # already inside this same zone - not a new entry

        self._inside_zone[tag_id] = zone_id
        return True  # either a fresh entry, or moved from one restricted zone into another


@dataclass
class InactivityState:
    """Tracks each tag's last position and how long it's been within
    MOVEMENT_EPSILON_M of that position, to detect prolonged stillness.
    Fires once per stillness episode - resets once the badge moves again,
    so a single continuous episode doesn't re-alert on every reading."""

    _last_position: dict = field(default_factory=dict)  # tag_id -> (x, y)
    _still_since: dict = field(default_factory=dict)  # tag_id -> epoch seconds
    _alerted: dict = field(default_factory=dict)  # tag_id -> bool, already alerted this episode

    # Placeholder - needs real calibration against the actual positioning
    # system's noise floor. Too small and normal Kalman-filter jitter on a
    # genuinely stationary badge will look like continuous "movement" and
    # this will never fire; too large and real small movements (someone
    # shifting in place) will be missed as "still".
    MOVEMENT_EPSILON_M = 1.0

    def check_inactivity(
        self, tag_id: str, x: float, y: float, now: float, threshold_seconds: float
    ) -> bool:
        """Returns True exactly once per stillness episode, when a tag has
        stayed within MOVEMENT_EPSILON_M of its position for at least
        threshold_seconds."""
        last = self._last_position.get(tag_id)
        self._last_position[tag_id] = (x, y)

        if last is None:
            # First reading for this tag - nothing to compare movement
            # against yet, start the stillness clock now.
            self._still_since[tag_id] = now
            self._alerted[tag_id] = False
            return False

        moved = math.hypot(x - last[0], y - last[1]) > self.MOVEMENT_EPSILON_M
        if moved:
            self._still_since[tag_id] = now
            self._alerted[tag_id] = False
            return False

        duration = now - self._still_since.get(tag_id, now)
        if duration >= threshold_seconds and not self._alerted.get(tag_id):
            self._alerted[tag_id] = True
            return True
        return False
