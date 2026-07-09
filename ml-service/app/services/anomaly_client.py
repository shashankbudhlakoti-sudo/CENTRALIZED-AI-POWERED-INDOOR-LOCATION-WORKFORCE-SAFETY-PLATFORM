"""
Reports a detected anomaly to the backend via POST /api/v1/anomalies/detect.
The backend decides severity and owns the actual insert into `alerts` -
same single-write-path pattern as positions and checkpoints. This service
never writes to alerts directly.
"""
import os
from typing import Optional
import httpx

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://backend.internal").rstrip("/")

async def report_anomaly(
    alert_type: str,
    bearer_token: str,
    employee_id: Optional[str] = None,
    tag_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    payload = {
        "alert_type": alert_type,
        "employee_id": employee_id,
        "tag_id": tag_id,
        "zone_id": zone_id,
        "details": details or {},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{BACKEND_BASE_URL}/api/v1/anomalies/detect",
            json=payload,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        resp.raise_for_status()
