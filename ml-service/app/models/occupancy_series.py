"""
Predictive analytics (Section 4.2, row 6): congestion/staffing forecasts
by zone and time.

The model doesn't forecast individual positions - it forecasts *occupancy
counts* (how many employees are in a zone) at regular time intervals,
since that's what's actually useful for staffing/congestion decisions.

This module builds that occupancy time series from raw position_events
(Track A's table) before any forecasting happens - Prophet (and any
time-series model) needs a clean, regularly-spaced series as input, not
raw scattered position pings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd


@dataclass
class OccupancySample:
    """One time-bucketed occupancy count for a zone."""
    timestamp: datetime  # bucket start, timezone-aware
    zone_id: str
    occupancy_count: int


class ZoneOccupancySeries:
    """Builds and holds a regular-interval occupancy series for one zone."""

    def __init__(self, zone_id: str, bucket_minutes: int = 15):
        self.zone_id = zone_id
        self.bucket_minutes = bucket_minutes
        self.samples: list[OccupancySample] = []

    @classmethod
    def from_position_events(
        cls,
        zone_id: str,
        events: list[dict],  # each: {"employee_id": str, "zone_id": str, "recorded_at": datetime}
        bucket_minutes: int = 15,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> "ZoneOccupancySeries":
        """Aggregates raw position events into regular time buckets, counting
        distinct employees present in the zone during each bucket.

        This is a simplification: it counts any employee who had at least
        one position event in the zone during the bucket, not continuous
        presence. Good enough for congestion forecasting; not a substitute
        for exact dwell-time analysis.
        """
        zone_events = [e for e in events if e["zone_id"] == zone_id]
        if not zone_events:
            raise ValueError(f"No position events found for zone '{zone_id}'")

        times = [e["recorded_at"] for e in zone_events]
        start = start or min(times)
        end = end or max(times)

        series = cls(zone_id, bucket_minutes)
        bucket = start.replace(second=0, microsecond=0)
        bucket = bucket - timedelta(minutes=bucket.minute % bucket_minutes)

        while bucket <= end:
            bucket_end = bucket + timedelta(minutes=bucket_minutes)
            employees_in_bucket = {
                e["employee_id"] for e in zone_events
                if bucket <= e["recorded_at"] < bucket_end
            }
            series.samples.append(OccupancySample(
                timestamp=bucket, zone_id=zone_id, occupancy_count=len(employees_in_bucket)
            ))
            bucket = bucket_end

        return series

    def to_dataframe(self) -> pd.DataFrame:
        """Prophet's required input shape: columns 'ds' (datetime) and 'y' (value)."""
        return pd.DataFrame({
            "ds": [s.timestamp.replace(tzinfo=None) for s in self.samples],  # Prophet wants naive datetimes
            "y": [s.occupancy_count for s in self.samples],
        })
