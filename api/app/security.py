"""Password hashing (bcrypt) and JWT issuing/verification."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.config import settings

# bcrypt only ever mixes the first 72 bytes of the input into its state, and
# bcrypt >= 5.0 refuses longer inputs outright instead of truncating. Enforce
# the cap at the API boundary (RegisterIn) rather than silently truncating.
PASSWORD_MAX_BYTES = 72

_DEFAULT_INSECURE_SECRET = "change-me-to-a-long-random-string"


def assert_security_config() -> None:
    """Fail fast on insecure security configuration (call once at startup).

    Dev/staging keep the well-known default secret so local runs stay
    friction-free; prod must never boot with it. Only HS256 is supported so a
    config typo can never cause tokens to be minted/accepted under an
    algorithm we did not pin (alg-confusion / "none" algorithm).
    """
    if settings.jwt_algorithm != "HS256":
        raise RuntimeError("settings.jwt_algorithm must be 'HS256'")
    if settings.env == "prod":
        problems: list[str] = []
        if settings.jwt_secret == _DEFAULT_INSECURE_SECRET or len(settings.jwt_secret) < 32:
            problems.append(
                "JWT_SECRET is the default placeholder or shorter than 32 chars — "
                'generate one: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if settings.admin_email == "admin@example.com":
            problems.append(
                "ADMIN_EMAIL is the default 'admin@example.com' — set a real admin address"
            )
        if problems:
            raise RuntimeError(
                "insecure ENV=prod configuration:\n  - " + "\n  - ".join(problems)
            )


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > PASSWORD_MAX_BYTES:
        raise ValueError(
            f"Password longer than bcrypt's {PASSWORD_MAX_BYTES}-byte limit; "
            "reject it at the API layer instead of truncating"
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    # Truncate to 72 bytes: bcrypt >= 5 raises on longer input instead of
    # truncating, which would turn every oversized login attempt into a
    # hard 401 even with the correct password. Hashes created under older
    # truncating bcrypt versions were made from exactly these first 72
    # bytes, so truncating here keeps them verifiable.
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:PASSWORD_MAX_BYTES], password_hash.encode()
        )
    except ValueError:
        return False


def _make_token(sub: str, token_type: str, expires_delta: timedelta, extra: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        **extra,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str = "user") -> str:
    return _make_token(
        user_id,
        "access",
        timedelta(minutes=settings.access_token_expire_minutes),
        {"role": role},
    )


def create_refresh_token(user_id: str) -> str:
    return _make_token(
        user_id, "refresh", timedelta(days=settings.refresh_token_expire_days), {}
    )


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Raise jwt.InvalidTokenError / jwt.ExpiredSignatureError on failure."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected {expected_type} token")
    return payload
