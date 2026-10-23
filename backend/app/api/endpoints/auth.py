"""Operator login: exchange the panel password for a signed JWT.

See app.security for the auth model. In dev mode (no operator_password set)
login still works and returns a token, so the panel behaves the same locally.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.schemas import LoginRequest, TokenResponse
from app.security import create_operator_token, require_operator, verify_operator_password

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(body: LoginRequest) -> TokenResponse:
    if not verify_operator_password(body.password):
        raise HTTPException(status_code=401, detail="Invalid password")
    return TokenResponse(
        access_token=create_operator_token(),
        expires_in=get_settings().jwt_ttl_minutes * 60,
    )


@router.get("/auth/me", dependencies=[Depends(require_operator)], tags=["Auth"])
def me() -> dict[str, bool]:
    """Cheap token-validity probe for the panel to check on load."""
    return {"authenticated": True}
