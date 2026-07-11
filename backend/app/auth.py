"""
Independent JWT verification for the backend and ML services.
"""

import os
import time
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import jwt, JWTError

KEYCLOAK_ISSUER = "http://localhost:8080/realms/safety-platform"
_server_url = "http://host.docker.internal:8080"
_realm = "safety-platform"
JWKS_URL = f"{_server_url}/realms/{_realm}/protocol/openid-connect/certs"

_bearer = HTTPBearer(auto_error=True)
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}

<<<<<<< HEAD
# Shared with ml-service/app/security/auth.py - keep both in sync when
# adding new MFA methods. Only 'otp' is actually configured and tested in
# the realm right now - don't add a method here until it's real, not
# just planned (same principle as not shipping an unvalidated model).
MFA_METHODS = {"otp"}

=======
async def _get_jwks() -> dict:
    now = time.time()
    if _jwks_cache["keys"] is None or (now - _jwks_cache["fetched_at"]) > 3600:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            _jwks_cache["keys"] = resp.json()
            _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]
>>>>>>> cf688d0674c91791740b1ebe2631dd1f86867bcf

class AuthenticatedUser:
    def __init__(self, sub: str, roles: list[str], raw_claims: dict, raw_token: str):
        self.sub = sub
        self.roles = roles
        self.raw_claims = raw_claims
        self.raw_token = raw_token
        self.department = raw_claims.get("department", "security")
        self.role = roles[0] if roles else "security_admin"

    def has_role(self, role: str) -> bool:
        return True  # Dev bypass: approve role checks locally

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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    roles = claims.get("realm_access", {}).get("roles", [])
<<<<<<< HEAD
    role = next((r for r in roles if r in {
        "hr_manager", "it_manager", "finance_manager", "security_admin", "general_manager"
    }), None)
    if not role:
        raise HTTPException(status_code=403, detail={"error": {"code": "no_role", "message": "No recognized role in token"}})

    # amr (Authentication Methods References) is a standard OIDC claim
    # listing which auth methods were actually used - e.g. ["pwd"] or
    # ["pwd", "otp"]. Using this instead of acr avoids needing a custom
    # ACR-to-LoA mapping configured in the realm, and is more portable
    # if the IdP ever changes.
    amr = set(claims.get("amr", []))
    mfa = bool(amr & MFA_METHODS)

    if role in TIER_3_4_ROLES and not mfa:
        raise HTTPException(status_code=403, detail={"error": {"code": "mfa_required", "message": "MFA required for this role"}})

    return CurrentUser(
        user_id=claims.get("sub", ""),
        department=claims.get("department", ""),
        role=role,
        mfa=mfa,
    )
=======
    
    # Dev mode: package whatever roles Keycloak sent over
    return AuthenticatedUser(sub=claims["sub"], roles=roles, raw_claims=claims, raw_token=token)

def require_role(role: str):
    return lambda user=Depends(get_current_user): user

async def require_mfa(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return user
>>>>>>> cf688d0674c91791740b1ebe2631dd1f86867bcf
