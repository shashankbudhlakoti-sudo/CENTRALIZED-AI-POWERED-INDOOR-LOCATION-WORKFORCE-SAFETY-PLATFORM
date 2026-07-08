"""
Periodic background sweep for tag_offline detection.

Unlike zone_breach/inactivity (checked synchronously as positions stream
in via /internal/filter-position), "a tag has gone silent" can only be
detected by an ABSENCE of events - there's no incoming request to hook
this into. Runs on a timer instead, reading tags.last_seen_at directly
(see zone_repo.find_stale_tags).

Authenticates to the backend using the ml-service Keycloak client
(client_credentials grant, see service_auth.py) rather than forwarding a
user's JWT, since there is no calling user for a background timer.
"""
import asyncio
import logging

from app.services import zone_repo
from app.services.anomaly_client import report_anomaly
from app.security.service_auth import get_service_token

logger = logging.getLogger("ml-service.tag_offline_sweep")

# Placeholders - need real values once we know the beacons' normal ping
# interval and acceptable network jitter. Too short and normal network
# hiccups will false-positive constantly; too long and a genuinely
# missing badge won't be caught quickly.
TAG_OFFLINE_THRESHOLD_SECONDS = 120
SWEEP_INTERVAL_SECONDS = 30

# Tracks which tags we've already reported offline, so we don't re-report
# every sweep cycle while a tag remains silent. Cleared automatically once
# a tag comes back online (see intersection_update below), so a future
# silence gets reported again rather than being permanently suppressed.
_already_reported_offline: set = set()


async def _sweep_once() -> None:
    stale = await zone_repo.find_stale_tags(TAG_OFFLINE_THRESHOLD_SECONDS)
    stale_ids = {t["tag_id"] for t in stale}

    _already_reported_offline.intersection_update(stale_ids)

    for tag in stale:
        if tag["tag_id"] in _already_reported_offline:
            continue
        try:
            token = await get_service_token()
            await report_anomaly(
                alert_type="tag_offline",
                bearer_token=token,
                employee_id=tag["employee_id"],
                tag_id=tag["tag_id"],
                details={
                    "tag_uid": tag["tag_uid"],
                    "last_seen_at": tag["last_seen_at"].isoformat() if tag["last_seen_at"] else None,
                    "threshold_seconds": TAG_OFFLINE_THRESHOLD_SECONDS,
                },
            )
            _already_reported_offline.add(tag["tag_id"])
        except Exception:
            # Don't let one tag's failed report (or the Keycloak client
            # not being set up yet) stop the sweep from checking the rest.
            logger.exception("failed to report tag_offline for tag=%s", tag["tag_id"])


async def run_forever() -> None:
    while True:
        try:
            await _sweep_once()
        except Exception:
            logger.exception("tag_offline sweep iteration failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
