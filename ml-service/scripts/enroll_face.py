"""
scripts/enroll_face.py — one-off manual enrollment for Task 4's first
real end-to-end test. NOT a route - role/workflow ownership for a real
enrollment endpoint is still an open question (see auth.py's comment).

Usage (inside the ml-service container):
    python scripts/enroll_face.py <employee_id> <path_to_photo.jpg>
"""
import asyncio
import sys

from app.db import get_pool
from app.services.embedding_backend import InsightFaceEmbeddingGenerator


async def enroll(employee_id: str, photo_path: str) -> None:
    with open(photo_path, "rb") as f:
        photo_bytes = f.read()

    generator = InsightFaceEmbeddingGenerator()
    embedding = await generator.generate(photo_bytes)

    if embedding is None:
        print(f"No face detected in {photo_path} - nothing written.")
        return

    print(f"Generated embedding, dim={embedding.shape[0]}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE employees
            SET face_embedding = $1, consent_given = TRUE, consent_given_at = now()
            WHERE id = $2
            """,
            embedding,
            employee_id,
        )
    print(f"DB result: {result}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/enroll_face.py <employee_id> <path_to_photo.jpg>")
        sys.exit(1)
    asyncio.run(enroll(sys.argv[1], sys.argv[2]))