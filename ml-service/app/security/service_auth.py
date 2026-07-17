"""
Client-credentials auth for the dedicated 'ml-service' Keycloak client.

Used by every call this service makes into the backend's service-only
endpoints (POST /api/v1/anomalies/detect, PATCH checkpoint match) as well
as the periodic tag_offline sweep. Backend's get_service_caller requires
the token's azp claim to be an approved service client - it rejects any
forwarded human user JWT regardless of which route triggered the call, so
AuthenticatedUser.raw_token is never valid here even for zone_breach,
inactivity, or checkpoint verification, all of which are triggered by an
already-authenticated human request. This module is the only valid source
of a token for any of those calls.

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
# Same "reachable from inside this container" concern as auth.py's JWKS
# fetch: in local dev, KEYCLOAK_ISSUER is localhost, which resolves to
# this container itself, not the host's Keycloak. Reuses the same
# KEYCLOAK_JWKS_BASE_URL env var auth.py already defines for exactly this
# purpose, rather than inventing a third variable for the same concern.
# Falls back to KEYCLOAK_ISSUER when unset, so this is a no-op in any
# environment where both hostnames already match (e.g. real deployment).
KEYCLOAK_TOKEN_BASE_URL = os.environ.get("KEYCLOAK_JWKS_BASE_URL", KEYCLOAK_ISSUER)
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

    if not KEYCLOAK_TOKEN_BASE_URL or not SERVICE_CLIENT_SECRET:
        raise RuntimeError(
            "KEYCLOAK_ISSUER / ML_SERVICE_CLIENT_SECRET not set - the dedicated "
            "'ml-service' Keycloak client hasn't been wired up yet. "
            "See app/security/service_auth.py docstring."
        )

    if _cached_token and time.time() < _cached_expiry:
        return _cached_token

    token_url = f"{KEYCLOAK_TOKEN_BASE_URL}/protocol/openid-connect/token"
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
