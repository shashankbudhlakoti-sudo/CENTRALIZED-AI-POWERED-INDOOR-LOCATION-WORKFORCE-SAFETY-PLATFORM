"""
Shared Postgres connection pool for this service.

Originally lived only in security/audit.py (for audit_log writes). Pulled
out here because anomaly detection now needs direct reads too (zones, tags)
via the same dedicated service-role connection - see the RLS discussion
with Shashank: this service reads cross-department data directly rather
than having every field forwarded through per-request payloads.
"""
import os
from typing import Optional

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool
