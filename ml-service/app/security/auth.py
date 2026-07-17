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

KEYCLOAK_ISSUER = os.environ["KEYCLOAK_ISSUER"]  # e.g. http://localhost:8080/realms/safety-platform
KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "ml-service")

# JWKS is fetched from a possibly different network path than the issuer
# claim itself - e.g. in local dev, the browser (and thus the token's `iss`)
# reaches Keycloak via localhost, but this service running inside Docker
# must reach the same Keycloak via host.docker.internal. KEYCLOAK_ISSUER
# is still the ONLY value used for the issuer claim check below - this
# split exists purely so the two concerns (reachability vs. claim identity)
# can't accidentally get coupled again.
KEYCLOAK_JWKS_BASE_URL = os.environ.get("KEYCLOAK_JWKS_BASE_URL", KEYCLOAK_ISSUER)
JWKS_URL = f"{KEYCLOAK_JWKS_BASE_URL}/protocol/openid-connect/certs"
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
# Defined once, here, and used by both get_current_user and require_mfa
# below - previously duplicated in two places, which is exactly how they
# could've silently drifted out of sync with each other.
MFA_REQUIRED_ROLES = {"security_admin", "general_manager"}

# Shared with backend/app/auth.py - keep both in sync when adding new MFA
# methods. Only 'otp' is actually configured and tested in the realm right
# now - don't add a method here until it's real, not just planned.
MFA_METHODS = {"otp"}

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}


def _has_mfa(claims: dict) -> bool:
    """amr (Authentication Methods References) is a standard OIDC claim
    listing which auth methods were actually used - e.g. ["pwd"] or
    ["pwd", "otp"]. Using this instead of acr avoids needing a custom
    ACR-to-LoA mapping configured in the realm, and is more portable if
    the IdP ever changes. Single source of truth for both call sites
    below, so there's only one place to update if the check changes."""
    amr = set(claims.get("amr", []))
    return bool(amr & MFA_METHODS)


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
    # A security_admin or general_manager token without a real MFA method
    # in `amr` is rejected here even if the backend somehow let it through.
    if any(r in MFA_REQUIRED_ROLES for r in roles) and not _has_mfa(claims):
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


async def require_mfa(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    """Note: get_current_user above already enforces MFA for every request
    from a Tier 3/4 role, so this dependency is currently redundant for
    those roles specifically - kept as an explicit, readable guard for any
    endpoint that wants to require MFA regardless of role (e.g. a
    lower-tier role performing an unusually sensitive action)."""
    if not _has_mfa(user.raw_claims):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires MFA - token was not issued with a multi-factor session",
        )
    return user
