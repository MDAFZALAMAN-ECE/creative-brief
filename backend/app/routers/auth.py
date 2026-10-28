import sqlite3
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..categories import seed_org
from ..config import settings
from ..database import audit, get_db
from ..errors import AppError
from ..security import ROLES, hash_password, require, sign_token, verify_password

router = APIRouter(prefix="/api/v1", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str
    org: str = ""


class MemberCreate(BaseModel):
    email: str
    password: str
    role: str


def _valid_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1] and len(email) <= 254


@router.post("/auth/register")
def register(body: Credentials, db: sqlite3.Connection = Depends(get_db)):
    email, org = body.email.strip().lower(), body.org.strip()
    if len(body.password) < 8:
        raise AppError(422, "Password must be 8+ chars")
    if not _valid_email(email) or not org:
        raise AppError(422, "A valid email and a new organization name are required")
    if db.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
        raise AppError(409, "Email exists")
    if db.execute("SELECT 1 FROM users WHERE lower(org)=lower(?)", (org,)).fetchone():
        raise AppError(403, "This organization already exists. Ask its administrator to create your account.")
    try:
        db.execute("INSERT INTO users(email,pw,role,org) VALUES(?,?,?,?)",
                   (email, hash_password(body.password), "admin", org))
        seed_org(db, org)
        db.commit()
    except sqlite3.IntegrityError:
        raise AppError(409, "Email or organization already exists")
    return {"role": "admin", "message": "Organization created. You are its administrator."}


@router.post("/auth/login")
def login(body: Credentials, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM users WHERE lower(email)=?", (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["pw"]):
        raise AppError(401, "Bad credentials")
    token = sign_token({"email": row["email"], "role": row["role"], "org": row["org"],
                        "exp": time.time() + settings.token_ttl_seconds})
    return {"token": token, "role": row["role"]}


@router.post("/admin/members")
def create_member(body: MemberCreate, user=Depends(require("admin")), db: sqlite3.Connection = Depends(get_db)):
    email = body.email.strip().lower()
    if not _valid_email(email):
        raise AppError(422, "A valid email is required")
    if len(body.password) < 8:
        raise AppError(422, "Password must be 8+ chars")
    if body.role not in ROLES - {"admin"}:
        raise AppError(422, "Invalid role")
    try:
        db.execute("INSERT INTO users(email,pw,role,org) VALUES(?,?,?,?)",
                   (email, hash_password(body.password), body.role, user["org"]))
    except sqlite3.IntegrityError:
        raise AppError(409, "Email already exists")
    audit(db, user, f"created member {email} role={body.role}")
    db.commit()
    return {"email": email, "role": body.role, "org": user["org"]}


@router.get("/admin/members")
def list_members(user=Depends(require("admin", "manager")), db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT email,role FROM users WHERE org=? ORDER BY email", (user["org"],))
    return [dict(r) for r in rows]
