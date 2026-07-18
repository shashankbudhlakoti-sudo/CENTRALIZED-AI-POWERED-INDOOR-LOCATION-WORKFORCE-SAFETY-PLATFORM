"""
Fetches enrolled (employee_id, face_embedding) pairs to compare a checkpoint
photo against.

employees.face_embedding (pgvector) is live as of the July 2026 migration
fixing its dimension to vector(512) to match InsightFace's buffalo_l
output (see embedding_backend.py). PostgresEnrolledEmbeddings.fetch_all()
below is the real implementation.

Note: this fetches ALL enrolled employees, not a similarity-filtered
subset - there's no query embedding available at fetch_all() time to
filter against (fetch_all() runs once per checkpoint trigger, then
face_match.py's find_best_match() does exact cosine scoring against the
full set). A pgvector `<=>` pre-filter only makes sense once real
enrollment counts are large enough that a full scan is a real cost -
revisit if/when the enrolled-employee count grows past a few hundred.
"""
from abc import ABC, abstractmethod

import numpy as np

from app.db import get_pool
from app.models.face_match import EnrolledEmbedding


class EnrolledEmbeddingsRepository(ABC):
    @abstractmethod
    async def fetch_all(self) -> list[EnrolledEmbedding]:
        raise NotImplementedError


class PostgresEnrolledEmbeddings(EnrolledEmbeddingsRepository):
    """Real Postgres-backed implementation. Requires the shared pool's
    connections to have the pgvector codec registered (see app/db.py's
    init callback) - without it, face_embedding decodes as a raw string,
    not a numpy array."""

    async def fetch_all(self) -> list[EnrolledEmbedding]:
            pool = await get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, face_embedding FROM employees
                    WHERE face_embedding IS NOT NULL
                      AND active = TRUE
                    """
                )
            return [
                EnrolledEmbedding(employee_id=str(r["id"]), embedding=r["face_embedding"].to_numpy())
                for r in rows
            ]


class InMemoryEnrolledEmbeddings(EnrolledEmbeddingsRepository):
    """Test/dev stand-in - lets the matching + endpoint logic be exercised
    end-to-end with fabricated enrollment data before Postgres support
    existed. Still useful for unit tests that shouldn't depend on a live DB."""

    def __init__(self, entries: list[EnrolledEmbedding] | None = None):
        self._entries = entries or []

    async def fetch_all(self) -> list[EnrolledEmbedding]:
        return self._entries