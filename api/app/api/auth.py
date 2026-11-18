"""Auth + per-user settings (JWT; PRD §2.8)."""

import logging
from datetime import UTC, datetime

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, select

from app.config import settings
from app.db.models import Setting, User
from app.db.session import get_session
from app.deps import get_current_user
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.cache import allow_rate

logger = logging.getLogger("bohurupi.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SettingsOut(BaseModel):
    theme: str
    default_lang: str
    default_voice_id: str
    speed: float
    auto_play: bool
    captions: bool
    engine_pref: str

    model_config = {"from_attributes": True}


class SettingsIn(BaseModel):
    theme: str | None = None
    default_lang: str | None = None
    default_voice_id: str | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    auto_play: bool | None = None
    captions: bool | None = None
    engine_pref: str | None = None


def _tokens_for(user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
        user=UserOut.model_validate(user),
    )


def _ensure_settings(session: Session, user: User) -> Setting:
    row = session.get(Setting, user.id)
    if row is None:
        row = Setting(user_id=user.id)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, session: Session = Depends(get_session)):
    if not allow_rate(body.email, "register", 10, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
    existing = session.exec(select(User).where(User.email == body.email.lower())).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        name=body.name,
        role="admin" if body.email.lower() == settings.admin_email.lower() else "user",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    _ensure_settings(session, user)
    return _tokens_for(user)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, session: Session = Depends(get_session)):
    if not allow_rate(body.email, "login", 20, 900):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
    user = session.exec(select(User).where(User.email == body.email.lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, session: Session = Depends(get_session)):
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
    except pyjwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from e
    user = session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return _tokens_for(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/settings", response_model=SettingsOut)
def get_settings_route(
    user: User = Depends(get_current_user), session: Session = Depends(get_session)
):
    return _ensure_settings(session, user)


@router.put("/settings", response_model=SettingsOut)
def put_settings(
    body: SettingsIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    row = _ensure_settings(session, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


# ---- Google OAuth (optional; enabled when GOOGLE_CLIENT_ID is set) ----


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google OAuth not configured")
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, session: Session = Depends(get_session)):
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Google OAuth not configured")
    from authlib.integrations.starlette_client import OAuth

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").lower()
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google login failed")
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(
            email=email,
            name=userinfo.get("name", ""),
            role="admin" if email == settings.admin_email.lower() else "user",
            created=datetime.now(UTC),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        _ensure_settings(session, user)
    tokens = _tokens_for(user)
    return RedirectResponse(f"{settings.web_origin}/oauth/callback#token={tokens.access_token}")
