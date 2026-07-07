"""
Fetches enrolled (employee_id, face_embedding) pairs to compare a checkpoint
photo against.

BLOCKED: employees.face_embedding is commented out pending pgvector being
re-added (per Shashank). Until then, EnrolledEmbeddingsRepository.fetch_all()
cannot do a real query - it raises NotImplementedError with a clear message
rather than silently returning an empty list, so a caller can't accidentally
treat "not built yet" as "zero enrolled employees" (which would make every
checkpoint a 'mismatch' for the wrong reason).

Once pgvector/face_embedding lands, implement PostgresEnrolledEmbeddings
below using a pgvector similarity query (e.g. `ORDER BY face_embedding <=>
%s LIMIT 20` to pre-filter candidates before exact cosine scoring in
face_match.py, rather than pulling every employee's embedding into memory
on every checkpoint trigger).
"""
from abc import ABC, abstractmethod

import numpy as np

from app.models.face_match import EnrolledEmbedding


class EnrolledEmbeddingsRepository(ABC):
    @abstractmethod
    async def fetch_all(self) -> list[EnrolledEmbedding]:
        raise NotImplementedError


class PostgresEnrolledEmbeddings(EnrolledEmbeddingsRepository):
    """Not yet implemented - blocked on employees.face_embedding /
    pgvector. Wire this up once that column is live; until then this
    raises loudly rather than pretending to work."""

    async def fetch_all(self) -> list[EnrolledEmbedding]:
        raise NotImplementedError(
            "employees.face_embedding is not live yet (pgvector pending). "
            "Cannot fetch enrolled embeddings for real matching. "
            "See app/services/enrolled_embeddings_repo.py."
        )


class InMemoryEnrolledEmbeddings(EnrolledEmbeddingsRepository):
    """Test/dev stand-in - lets the matching + endpoint logic be exercised
    end-to-end with fabricated enrollment data before Postgres support
    exists."""

    def __init__(self, entries: list[EnrolledEmbedding] | None = None):
        self._entries = entries or []

    async def fetch_all(self) -> list[EnrolledEmbedding]:
        return self._entries
