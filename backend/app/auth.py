import os
from fastapi import Header, HTTPException
from jose import jwt, JWTError

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "safety-platform")

TIER_3_4_ROLES = {"security_admin", "general_manager"}


class CurrentUser:
    def __init__(self, user_id: str, department: str, role: str, mfa: bool):
        self.user_id = user_id
        self.department = department
        self.role = role
        self.mfa = mfa


def get_current_user(authorization: str = Header(...)) -> CurrentUser:
    """
    Decodes and validates the Keycloak-issued JWT.
    NOTE: in production, fetch and cache the realm's JWKS from
    {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs
    and verify signature properly. This skeleton decodes without
    signature verification for local dev only — replace before any
    real deployment (Phase 8 hardening).
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": {"code": "no_token", "message": "Missing bearer token"}})

    token = authorization.split(" ", 1)[1]

    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "bad_token", "message": "Invalid token"}})

    roles = claims.get("realm_access", {}).get("roles", [])
    role = next((r for r in roles if r in {
        "hr_manager", "it_manager", "finance_manager", "security_admin", "general_manager"
    }), None)

    if not role:
        raise HTTPException(status_code=403, detail={"error": {"code": "no_role", "message": "No recognized role in token"}})

    mfa = claims.get("acr") == "mfa"
    if role in TIER_3_4_ROLES and not mfa:
        raise HTTPException(status_code=403, detail={"error": {"code": "mfa_required", "message": "MFA required for this role"}})

    return CurrentUser(
        user_id=claims.get("sub", ""),
        department=claims.get("department", ""),
        role=role,
        mfa=mfa,
    )
