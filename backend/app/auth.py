"""
Independent JWT verification for the backend and ML services.

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

# Hardcode the precise token issuer representation
KEYCLOAK_ISSUER = "http://localhost:8080/realms/safety-platform"

# Force the container network routing to check the host bridge endpoint
_server_url = "http://host.docker.internal:8080"
_realm = "safety-platform"
JWKS_URL = f"{_server_url}/realms/{_realm}/protocol/openid-connect/certs"

KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "account")
JWKS_CACHE_TTL_SECONDS = 3600

_bearer = HTTPBearer(auto_error=True)

ALLOWED_ROLES = {"security_admin", "hr_manager", "it_manager", "general_manager", "finance_manager"}
MFA_REQUIRED_ROLES = {"security_admin", "general_manager"}
MFA_METHODS = {"otp"}

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
        self.raw_token = raw_token

    def has_role(self, role: str) -> bool:
        return role in self.roles

CurrentUser = AuthenticatedUser


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> AuthenticatedUser:
    token = credentials.credentials
    jwks = await _get_jwks()

    try:
        unverified_header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == unverified_header.get("kid")), None)
        if key is None:
            _jwks_cache["keys"] = None
            jwks = await _get_jwks()
            key = next((k for k in jwks["keys"] if k["kid"] == unverified_header.get("kid")), None)
            if key is None:
                raise JWTError("Signing key not found")

        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=KEYCLOAK_ISSUER,
            options={"require_exp": True, "require_iat": True, "verify_aud": False},
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
            detail="Role not permitted to access the service",
        )

    amr = set(claims.get("amr", []))
    mfa_verified = bool(amr & MFA_METHODS)

    if any(r in MFA_REQUIRED_ROLES for r in roles) and not mfa_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "mfa_required", "message": "MFA required for this role"}},
        )

    return AuthenticatedUser(sub=claims["sub"], roles=roles, raw_claims=claims, raw_token=token)


def require_role(role: str):
    async def _checker(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {role}",
            )
        return user
    return _checker


async def require_mfa(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    amr = set(user.raw_claims.get("amr", []))
    if any(r in MFA_REQUIRED_ROLES for r in user.roles) and not (amr & MFA_METHODS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role requires MFA - token was not issued with a multi-factor session",
        )
    return user
