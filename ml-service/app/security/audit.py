"""
Audit logging for the ML service.

Section 8 of the project spec requires a full audit trail of who accessed
whose data, enforceable even against the highest-privilege role. Every
on-demand AI call (NL query, checkpoint verification) that touches an
individual employee's data MUST be logged here before the result is
returned - not as an afterthought.

This writes to the shared `audit_log` table (owned by Track A's schema) so
there is exactly one audit trail for the whole system, not a second one
only ML actions show up in.
"""

import os
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"]

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def log_action(
    user_id: str,
    action: str,
    target_employee_id: str | None,
    reason_code: str,
) -> None:
    """Every ML-service action that touches employee data calls this.

    action examples: 'nl_query', 'checkpoint_verify', 'anomaly_alert_raised'
    reason_code: short machine-readable reason, e.g. 'manager_query',
    'scheduled_gate_check', 'break_glass'
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO audit_log (user_id, action, target_employee_id, timestamp, reason_code)
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_id,
            action,
            target_employee_id,
            datetime.now(timezone.utc),
            reason_code,
        )
