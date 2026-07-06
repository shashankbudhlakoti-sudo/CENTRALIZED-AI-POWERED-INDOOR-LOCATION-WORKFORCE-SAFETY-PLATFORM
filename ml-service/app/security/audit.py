"""
Audit logging for the ML service.

Section 8 of the project spec requires a full audit trail of who accessed
whose data, enforceable even against the highest-privilege role. Every
on-demand AI call (NL query, checkpoint verification) that touches an
individual employee's data MUST be logged here before the result is
returned - not as an afterthought.

Column names match the shared /contracts/schema.sql exactly (Track A owns
that table's schema) - this file writes to the SAME audit_log table the
backend writes to, so there is one audit trail for the whole system.
"""

import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def log_action(
    actor_user_id: str,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    justification: Optional[str] = None,
    grant_type: str = "normal",
    ip_address: Optional[str] = None,
    grant_expires_at: Optional[datetime] = None,
) -> None:
    """Every ML-service action that touches employee data calls this.

    action examples: 'read', 'nl_query', 'checkpoint_verify', 'model_retrain'
    resource_type: 'employee' | 'position_events' | 'alerts' | 'model', etc.
    actor_role must be one of the schema's user_role enum values
    ('hr_manager','it_manager','finance_manager','security_admin','general_manager')
    - Postgres will reject the insert if it isn't, which is the correct
      failure mode (better a rejected log write than a silently wrong one).

    grant_expires_at: required for break-glass / delegated access grants
    ('break_glass' or 'delegated' grant_type) — records when that elevated
    access expires, so expiry is enforceable and auditable, not just
    logged as a type. Left as None for normal-role actions.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_log
                (actor_user_id, actor_role, action, resource_type, resource_id,
                 justification, grant_type, grant_expires_at, created_at, ip_address)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            actor_user_id,
            actor_role,
            action,
            resource_type,
            resource_id,
            justification,
            grant_type,
            grant_expires_at,
            datetime.now(timezone.utc),
            ip_address,
        )
