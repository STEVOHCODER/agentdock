import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import APIKey, User, UserSession, utcnow


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    raw = secrets.token_urlsafe(36)
    token_id = hashlib.sha256(raw.encode()).hexdigest()
    db.add(UserSession(id=token_id, user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().session_days)))
    user.last_login_at = utcnow()
    return raw


def issue_api_key(db: Session, user: User, name: str, scopes: list[str] | None = None) -> str:
    raw = "adk_" + secrets.token_urlsafe(32)
    prefix = raw[:12]
    db.add(APIKey(user_id=user.id, name=name, prefix=prefix, key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                  scopes=scopes or ["skills:read", "library:read", "library:write", "account:read",
                                    "teams:read", "marketplace:read"]))
    return raw


def current_user(request: Request, db: Session, allow_key: bool = True) -> User:
    authorization = request.headers.get("authorization", "")
    if allow_key and authorization.startswith("Bearer adk_"):
        raw = authorization[7:]
        api_key = db.scalar(select(APIKey).where(APIKey.key_hash == hashlib.sha256(raw.encode()).hexdigest(), APIKey.revoked_at.is_(None)))
        if api_key:
            user = db.get(User, api_key.user_id)
            if user and user.is_active:
                request.state.api_key_scopes = api_key.scopes or []
                api_key.last_used_at = datetime.now(timezone.utc)
                db.commit()
                return user
    raw_session = request.cookies.get("agentdock_session")
    if raw_session:
        sid = hashlib.sha256(raw_session.encode()).hexdigest()
        session = db.get(UserSession, sid)
        expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session and session.expires_at.tzinfo is None else (session.expires_at if session else None)
        if session and expires_at and expires_at > datetime.now(timezone.utc):
            user = db.get(User, session.user_id)
            if user and user.is_active:
                return user
    raise HTTPException(status_code=401, detail="Sign in to continue")


def optional_user(request: Request, db: Session) -> User | None:
    try:
        return current_user(request, db)
    except HTTPException:
        return None


def admin_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    key_scopes = getattr(request.state, "api_key_scopes", None)
    if key_scopes is not None and "admin:*" not in key_scopes:
        raise HTTPException(status_code=403, detail="Administrator API key scope required")
    if user.role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def require_scope(request: Request, scope: str) -> None:
    key_scopes = getattr(request.state, "api_key_scopes", None)
    if key_scopes is not None and scope not in key_scopes:
        raise HTTPException(status_code=403, detail=f"API key requires the {scope} scope")
