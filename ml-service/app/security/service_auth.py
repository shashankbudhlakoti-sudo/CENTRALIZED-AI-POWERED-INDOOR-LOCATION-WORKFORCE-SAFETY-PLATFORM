"""
Client-credentials auth for the dedicated 'ml-service' Keycloak client.

Used ONLY by processes with no inbound authenticated request to forward a
token from - currently, that's just the periodic tag_offline sweep
(tag_offline_sweep.py). Everything else in this service (zone_breach,
inactivity, checkpoint verification) reuses the calling request's own JWT
via AuthenticatedUser.raw_token, since those are always triggered by an
already-authenticated call. This module exists specifically for the case
where there is no calling request at all.

Setup (Shashank, in progress): a separate 'ml-service' Keycloak client
(not reusing safety-platform-api - human-facing and service-facing
clients stay separate), Client authentication + Service accounts roles
enabled, Direct access grants off (no username/password needed), assigned
a dedicated 'service_account' role rather than security_admin so audit
entries can distinguish the automated sweep from a human admin action.
"""
import os
import time
from typing import Optional

import httpx

KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER")  # same var auth.py uses, e.g. https://auth.internal/realms/airport
SERVICE_CLIENT_ID = os.environ.get("ML_SERVICE_CLIENT_ID", "ml-service")
SERVICE_CLIENT_SECRET = os.environ.get("ML_SERVICE_CLIENT_SECRET")  # pending Shashank's Keycloak setup

_cached_token: Optional[str] = None
_cached_expiry: float = 0.0


async def get_service_token() -> str:
    """Returns a cached client-credentials token, refreshing shortly
    before expiry. Raises clearly (rather than failing silently or with
    a confusing HTTP error) if the client secret hasn't been configured
    yet - expected until the 'ml-service' Keycloak client exists."""
    global _cached_token, _cached_expiry

    if not KEYCLOAK_ISSUER or not SERVICE_CLIENT_SECRET:
        raise RuntimeError(
            "KEYCLOAK_ISSUER / ML_SERVICE_CLIENT_SECRET not set - the dedicated "
            "'ml-service' Keycloak client hasn't been wired up yet. "
            "See app/security/service_auth.py docstring."
        )

    if _cached_token and time.time() < _cached_expiry:
        return _cached_token

    token_url = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": SERVICE_CLIENT_ID,
                "client_secret": SERVICE_CLIENT_SECRET,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _cached_token = data["access_token"]
    # Refresh 30s early so a request never races the token expiring mid-flight.
    _cached_expiry = time.time() + data.get("expires_in", 60) - 30
    return _cached_token
