"""
Writes a newly-generated face embedding back to the backend, per the same
single-writer-per-field pattern as checkpoint_client.py: ml-service never
writes to Postgres directly for employees.face_embedding either - the
backend owns that column and the actual write.
"""
import os
import httpx

BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://backend.internal").rstrip("/")


async def patch_employee_face_embedding(
    employee_id: str,
    embedding: list[float],
    service_token: str,
) -> None:
    url = f"{BACKEND_BASE_URL}/api/v1/employees/{employee_id}/face-embedding"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.patch(
            url,
            json={"embedding": embedding},
            headers={"Authorization": f"Bearer {service_token}"},
        )
        resp.raise_for_status()