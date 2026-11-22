"""Auth + per-user settings (JWT; PRD §2.8)."""

import asyncio
import logging
from datetime import datetime

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlmodel import Session, select

from app.config import settings
from app.db.models import Setting, User
from app.db.session import get_session
from app.deps import get_current_user
from app.security import (
    PASSWORD_MAX_BYTES,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.cache import allow_rate, cache

logger = logging.getLogger("bohurupi.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# Per-IP caps complement the per-email limits: an attacker rotating emails
# (credential stuffing) or a bot hits one bucket per source address. Behind a
# trusted reverse proxy, prefer the real client IP (X-Forwarded-For) instead
# of the proxy address (see audit report).
LOGIN_IP_LIMIT, LOGIN_IP_WINDOW = 60, 900
REGISTER_IP_LIMIT, REGISTER_IP_WINDOW = 100, 3600
REFRESH_IP_LIMIT, REFRESH_IP_WINDOW = 120, 900


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)

    @field_validator("password")
    @classmethod
    def _password_fits_bcrypt(cls, v: str) -> str:
        # bcrypt only mixes the first 72 bytes; longer inputs are rejected
        # outright by bcrypt >= 5 (previously truncated silently).
        if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
            raise ValueError(
                f"Password must be at most {PASSWORD_MAX_BYTES} bytes "
                "(non-Latin characters use several bytes each)"
            )
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class MessageOut(BaseModel):
    message: str
    # dev-only convenience when SMTP isn't configured (never in prod)
    dev_token: str | None = None
    dev_url: str | None = None


class DemoAccountOut(BaseModel):
    email: str
    name: str
    label: str


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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _allow_ip(request: Request, bucket: str, limit: int, window: int) -> bool:
    return allow_rate(f"ip:{_client_ip(request)}", bucket, limit, window)


def _ensure_settings(session: Session, user: User) -> Setting:
    row = session.get(Setting, user.id)
    if row is None:
        row = Setting(user_id=user.id)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


@router.post("/register", response_model=TokenOut, status_code=201)
def register(request: Request, body: RegisterIn, session: Session = Depends(get_session)):
    if not allow_rate(body.email, "register", 10, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
    if not _allow_ip(request, "register-ip", REGISTER_IP_LIMIT, REGISTER_IP_WINDOW):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts from this network"
        )
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
def login(request: Request, body: LoginIn, session: Session = Depends(get_session)):
    if not allow_rate(body.email, "login", 20, 900):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
    if not _allow_ip(request, "login-ip", LOGIN_IP_LIMIT, LOGIN_IP_WINDOW):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts from this network"
        )
    user = session.exec(select(User).where(User.email == body.email.lower())).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, body: RefreshIn, session: Session = Depends(get_session)):
    if not _allow_ip(request, "refresh-ip", REFRESH_IP_LIMIT, REFRESH_IP_WINDOW):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts")
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
    if userinfo.get("email_verified") is not True:
        # The email claim is the account identity (and can match admin_email):
        # only accept verified Google emails, else an attacker controlling an
        # unverified alias could take over an existing account.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google email is not verified")
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(
            email=email,
            name=userinfo.get("name", ""),
            role="admin" if email == settings.admin_email.lower() else "user",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        _ensure_settings(session, user)
    tokens = _tokens_for(user)
    # refresh token rides along so OAuth sessions survive past the 30-min access token
    return RedirectResponse(
        f"{settings.web_origin}/oauth/callback"
        f"#token={tokens.access_token}&refresh={tokens.refresh_token}"
    )


# ---- Demo account (dev/staging only — never a production backdoor) ----


@router.get("/demo-accounts", response_model=list[DemoAccountOut])
def demo_accounts():
    if not settings.demo_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo mode is disabled")
    return [
        DemoAccountOut(
            email=settings.demo_email.lower(),
            name=settings.demo_name,
            label="Demo account · free plan",
        )
    ]


@router.post("/demo-login", response_model=TokenOut)
def demo_login(session: Session = Depends(get_session)):
    if not settings.demo_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo mode is disabled")
    user = session.exec(
        select(User).where(User.email == settings.demo_email.lower())
    ).first()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo account is unavailable")
    return _tokens_for(user)


# ---- Email-only password reset ----


def _reset_key(token_digest: str) -> str:
    return f"pwdreset:{token_digest}"


def _send_reset_email(to: str, link: str) -> bool:
    """Send via SMTP when configured. Returns False when delivery isn't set up."""
    if not settings.smtp_host:
        return False
    import smtplib
    from email.message import EmailMessage

    try:
        msg = EmailMessage()
        msg["Subject"] = "Reset your Bohurupi password"
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg.set_content(
            f"Use this link to choose a new password (valid for 15 minutes):\n\n{link}\n\n"
            "If you didn't request this, ignore this message."
        )
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return True
    except Exception:
        logger.exception("Could not send password-reset email")
        return False


@router.post("/forgot-password", response_model=MessageOut)
async def forgot_password(
    body: ForgotIn, request: Request, session: Session = Depends(get_session)
):
    if not allow_rate(body.email, "forgot", 5, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many reset requests")
    host = _client_ip(request)
    if not allow_rate(host, "forgot-ip", 20, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many reset requests")

    generic = "If an account exists, a reset link has been sent."
    user = session.exec(select(User).where(User.email == body.email.lower())).first()
    if user is None or not user.password_hash:
        return MessageOut(message=generic)  # no account enumeration

    import hashlib
    import secrets

    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    cache().set(_reset_key(digest), user.id, ttl=900)
    link = f"{settings.web_origin}/reset-password?token={token}"
    sent = await asyncio.to_thread(_send_reset_email, user.email, link)
    if sent:
        return MessageOut(message=generic)
    if settings.demo_enabled:
        # local dev convenience: no SMTP configured, surface the link in dev only
        return MessageOut(message=generic, dev_token=token, dev_url=link)
    # production without SMTP must fail honestly rather than claim a sent email
    cache().delete(_reset_key(digest))
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Password reset email is not configured on this deployment.",
    )


@router.post("/reset-password", response_model=MessageOut)
def reset_password(body: ResetIn, session: Session = Depends(get_session)):
    import hashlib

    from app.security import PASSWORD_MAX_BYTES

    if len(body.new_password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at most {PASSWORD_MAX_BYTES} bytes",
        )
    digest = hashlib.sha256(body.token.encode()).hexdigest()
    key = _reset_key(digest)
    user_id = cache().get(key)
    if not user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset link is invalid or expired")
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Reset link is invalid or expired")
    user.password_hash = hash_password(body.new_password)
    session.add(user)
    session.commit()
    cache().delete(key)  # single use
    return MessageOut(message="Password updated. You can sign in now.")
