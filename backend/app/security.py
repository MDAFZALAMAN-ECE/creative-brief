"""Password hashing, signed tokens and role-based access dependencies."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time

from fastapi import Depends, Header

from .config import settings
from .database import get_db
from .errors import AppError

ROLES = {"admin", "manager", "creator", "reviewer"}
_PBKDF2_ROUNDS = 200_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt = stored.split("$", 1)[0]
    except Exception:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def _mac(body: str) -> str:
    return hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()


def sign_token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return f"{body}.{_mac(body)}"


def decode_token(token: str) -> dict:
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(sig, _mac(body)):
            raise ValueError("bad signature")
        data = json.loads(base64.urlsafe_b64decode(body))
        if data["exp"] <= time.time():
            raise ValueError("expired")
        return data
    except Exception:
        raise AppError(401, "Not authenticated")


def current_user(authorization: str | None = Header(None),
                 db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Validate the bearer token, then re-read the user's role so role changes apply immediately."""
    if not authorization:
        raise AppError(401, "Not authenticated")
    claims = decode_token(authorization.removeprefix("Bearer ").strip())
    row = db.execute("SELECT email, role, org FROM users WHERE email=? AND org=?",
                     (claims.get("email"), claims.get("org"))).fetchone()
    if not row:
        raise AppError(401, "Not authenticated")
    return {"email": row["email"], "role": row["role"], "org": row["org"]}


def require(*roles: str):
    """Dependency factory: `Depends(require("admin", "manager"))`."""
    def checker(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise AppError(403, f"Requires role: {', '.join(roles)}")
        return user
    return checker
