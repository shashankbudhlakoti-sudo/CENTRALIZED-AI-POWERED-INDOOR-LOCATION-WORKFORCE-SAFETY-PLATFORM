"""
Direct Postgres reads of zones/tags for anomaly detection - the ML
service's own dedicated service-role DB access, confirmed with Shashank:
"is this position inside a restricted zone" is a spatial containment
check PostGIS already does efficiently, so this service queries directly
rather than having the backend forward a flag on every position event.

Read-only. This module never writes to zones or tags.
"""
from typing import Optional

from app.db import get_pool


async def find_restricted_zone_containing(x: float, y: float) -> Optional[dict]:
    """Returns {'zone_id': ..., 'name': ...} if (x, y) falls inside a zone
    with zone_type='restricted', else None.

    geom is a local-plane polygon (meters, SRID 0) - same coordinate
    system as position_events.x/y, confirmed with Shashank, so no
    coordinate transform is needed before the containment check.

    zone_type is a plain VARCHAR (not a DB-enforced enum) per schema.sql -
    filtering on the exact string 'restricted' by convention, matching
    the comment in schema.sql listing the valid values.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, name FROM zones
            WHERE zone_type = 'restricted'
              AND ST_Contains(geom, ST_MakePoint($1, $2))
            LIMIT 1
            """,
            x,
            y,
        )
    if row is None:
        return None
    return {"zone_id": str(row["id"]), "name": row["name"]}


async def get_tag_employee(tag_id: str) -> Optional[str]:
    """tags.employee_id is nullable - a tag can exist unassigned, per
    schema.sql. Returns None in that case rather than raising."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT employee_id FROM tags WHERE id = $1", tag_id)
    if row is None or row["employee_id"] is None:
        return None
    return str(row["employee_id"])


async def find_stale_tags(silent_after_seconds: float) -> list[dict]:
    """Active tags whose last_seen_at is older than silent_after_seconds.
    Used by the periodic tag_offline sweep (tag_offline_sweep.py) - this
    is the one anomaly check that can't be triggered by an incoming
    position event, since it's detecting the ABSENCE of one."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, tag_uid, employee_id, last_seen_at FROM tags
            WHERE active = TRUE
              AND last_seen_at IS NOT NULL
              AND last_seen_at < now() - make_interval(secs => $1)
            """,
            silent_after_seconds,
        )
    return [
        {
            "tag_id": str(r["id"]),
            "tag_uid": r["tag_uid"],
            "employee_id": str(r["employee_id"]) if r["employee_id"] else None,
            "last_seen_at": r["last_seen_at"],
        }
        for r in rows
    ]
