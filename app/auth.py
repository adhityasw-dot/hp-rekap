import hashlib
import hmac
import secrets
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy.orm import Session
from fastapi import Request

from .config import COOKIE_SECURE, SECRET_KEY
from .database import get_db
from .models import User

_serializer = URLSafeSerializer(SECRET_KEY, salt="hp-rekap-session")
COOKIE_NAME = "hp_rekap_session"


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 (tanpa dependensi passlib/bcrypt yang rewel di Py3.14)."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    )
    return f"pbkdf2_sha256$120000${salt}${dk.hex()}"


def verify_password(plain: str, hashed: str) -> bool:
    try:
        algo, rounds, salt, digest = hashed.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", plain.encode("utf-8"), salt.encode("utf-8"), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def create_session_token(username: str) -> str:
    return _serializer.dumps({"u": username})


def read_session_token(token: str) -> Optional[str]:
    try:
        data = _serializer.loads(token)
        return data.get("u")
    except BadSignature:
        return None


def get_optional_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    username = read_session_token(token)
    if not username:
        return None
    return db.query(User).filter(User.username == username).first()


def set_login_cookie(response, username: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(username),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
