"""
Independent JWT verification for the ML service.

Design principle: this service NEVER trusts that a request "came from the
backend, so it must be fine." Every request is verified against Keycloak's
public keys (JWKS) directly. If the backend is ever compromised or
misconfigured, this service still refuses unauthorized or expired tokens.

Keycloak signs tokens with RS256. We fetch and cache its public keys (JWKS)
rather than storing any shared secret in this service.
"""

import os
import time
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError

KEYCLOAK_ISSUER = os.environ["KEYCLOAK_ISSUER"]  # e.g. https://auth.internal/realms/airport
KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "ml-service")
JWKS_URL = f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs"
JWKS_CACHE_TTL_SECONDS = 3600

_bearer = HTTPBearer(auto_error=True)

# Roles allowed to call the ML service at all. Fine-grained per-endpoint
# checks happen in the route itself (e.g. only security_admin can call
# checkpoint verification).
ALLOWED_ROLES = {"security_admin", "hr_manager", "it_manager", "general_manager"}

# Per the shared API contract (contracts/api-spec.md): Tier 3/4 roles must
# have completed MFA. The backend enforces this too, but this service does
# not trust that enforcement happened upstream - same "verify everything
# independently" principle as JWT verification itself.
MFA_REQUIRED_ROLES = {"security_admin", "general_manager"}

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}


async def _get_jwks() -> dict:
    now = time.time()
    if _jwks_cache["keys"] is None or (now - _jwks_cache["fetched_at"]) > JWKS_CACHE_TTL_SECONDS:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            _jwks_cache["keys"] = resp.json()
            _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


class AuthenticatedUser:
    def __init__(self, sub: str, roles: list[str], raw_claims: dict, raw_token: str):
        self.sub = sub
        self.roles = roles
        self.raw_claims = raw_claims
        self.raw_token = raw_token  # forwarded when this service itself calls
        # the backend (e.g. PATCH /checkpoints/{id}/match) - reuses the
        # caller's own Keycloak session rather than minting a separate
        # service credential, since it's the same realm/audience.

    def has_role(self, role: str) -> bool:
        return role in self.roles


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> AuthenticatedUser:
    token = credentials.credentials
    jwks = await _get_jwks()

    try:
        unverified_header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == unverified_header.get("kid")), None)
        if key is None:
            # Key rotated since our cache was populated - force a refresh once.
            _jwks_cache["keys"] = None
            jwks = await _get_jwks()
            key = next((k for k in jwks["keys"] if k["kid"] == unverified_header.get("kid")), None)
            if key is None:
                raise JWTError("Signing key not found")

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=KEYCLOAK_AUDIENCE,
            issuer=KEYCLOAK_ISSUER,
            options={"require_exp": True, "require_iat": True},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    roles: list[str] = claims.get("realm_access", {}).get("roles", [])
    if not any(r in ALLOWED_ROLES for r in roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Role not permitted to access the ML service",
        )

    # Independent MFA check for Tier 3/4 roles (contracts/api-spec.md).
    # A security_admin or general_manager token without acr=mfa is rejected
    # here even if the backend somehow let it through.
    if any(r in MFA_REQUIRED_ROLES for r in roles) and claims.get("acr") != "mfa":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA required for this role",
        )

    return AuthenticatedUser(sub=claims["sub"], roles=roles, raw_claims=claims, raw_token=token)


def require_role(*allowed_roles: str):
    """Dependency factory for endpoint-level role checks, e.g.:
    @router.post("/checkpoint/verify", dependencies=[Depends(require_role("security_admin"))])

    Accepts multiple roles when any one of them should be allowed, e.g.
    require_role("security_admin", "hr_manager") - added for face
    enrollment, where it's genuinely unclear yet which role should own it.
    """

    async def _checker(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not any(user.has_role(r) for r in allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {', '.join(allowed_roles)}",
            )
        return user

    return _checker


# Contract (contracts/api-spec.md): Tier 3/4 roles (security_admin,
# general_manager) require MFA - backend rejects tokens without it on
# protected endpoints. The ML service enforces this independently too,
# rather than trusting that the backend already checked - the same
# defense-in-depth principle as verifying the JWT signature ourselves.
MFA_REQUIRED_ROLES = {"security_admin", "general_manager"}


async def require_mfa(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    needs_mfa = any(r in MFA_REQUIRED_ROLES for r in user.roles)
    if needs_mfa and user.raw_claims.get("acr") != "mfa":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role requires MFA - token was not issued with a multi-factor session",
        )
    return user
