"""
Writes the face-match result back to the backend via PATCH, per the agreed
single-writer-per-field split: the backend creates the checkpoint_events
row (zone_id, tag_id, employee_id, photo_url) and owns resolved_at; this
service owns match_employee_id, match_confidence, match_status and never
writes to Postgres for this table directly.
"""
import os

import httpx

from app.models.face_match import MatchResult

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://backend.internal")


async def patch_checkpoint_match(
    checkpoint_event_id: str,
    result: MatchResult,
    service_token: str,
) -> None:
    url = f"{BACKEND_BASE_URL}/checkpoints/{checkpoint_event_id}/match"
    payload = {
        "match_employee_id": result.match_employee_id,
        "match_confidence": result.match_confidence,
        "match_status": result.match_status,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {service_token}"},
        )
        resp.raise_for_status()
