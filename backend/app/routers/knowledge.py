"""Categories, category->collection mappings and the guideline library."""
import re
import sqlite3

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from ..categories import COLLECTIONS, seed_org
from ..config import settings
from ..database import audit, get_db
from ..errors import AppError
from ..extraction import chunk_text, extract_pages
from ..retrieval import rank
from ..security import current_user, require

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
MANAGERS = ("admin", "manager")


class CategoryCreate(BaseModel):
    key: str
    name: str
    description: str = ""
    collections: list[str] = ["custom"]


class CategoryUpdate(BaseModel):
    name: str
    description: str = ""
    active: bool = True


class MappingUpdate(BaseModel):
    collections: list[str]


def _check_collections(collections: list[str]) -> None:
    if any(c not in COLLECTIONS for c in collections):
        raise AppError(422, "Unknown guideline collection")


def _require_category(db, org: str, key: str) -> None:
    if not db.execute("SELECT 1 FROM categories WHERE org=? AND key=?", (org, key)).fetchone():
        raise AppError(404, "Unknown category key")


@router.get("/collections")
def list_collections(user=Depends(current_user)):
    return COLLECTIONS


@router.get("/categories")
def get_categories(user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    seed_org(db, user["org"])
    db.commit()
    rows = db.execute("SELECT key,name,description,active FROM categories WHERE org=? ORDER BY name", (user["org"],))
    return [dict(r) for r in rows]


@router.post("/categories")
def create_category(body: CategoryCreate, user=Depends(require(*MANAGERS)), db: sqlite3.Connection = Depends(get_db)):
    key = body.key.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,49}", key):
        raise AppError(422, "Category key must be 2-50 lowercase letters, digits, or underscores and start with a letter")
    _check_collections(body.collections)
    seed_org(db, user["org"])
    try:
        db.execute("INSERT INTO categories(org,key,name,description,active) VALUES(?,?,?,?,1)",
                   (user["org"], key, body.name.strip()[:100], body.description[:1000]))
    except sqlite3.IntegrityError:
        raise AppError(409, "Category key already exists")
    for collection in dict.fromkeys(body.collections or ["custom"]):
        db.execute("INSERT INTO category_mappings(org,category_key,collection) VALUES(?,?,?)",
                   (user["org"], key, collection))
    audit(db, user, f"created category {key}")
    db.commit()
    return {"key": key, "created": True}


@router.put("/categories/{key}")
def update_category(key: str, body: CategoryUpdate, user=Depends(require(*MANAGERS)),
                    db: sqlite3.Connection = Depends(get_db)):
    seed_org(db, user["org"])
    _require_category(db, user["org"], key)
    db.execute("UPDATE categories SET name=?,description=?,active=? WHERE org=? AND key=?",
               (body.name.strip()[:100], body.description[:1000], int(body.active), user["org"], key))
    audit(db, user, f"updated category {key}")
    db.commit()
    return {"key": key, "updated": True}


@router.get("/category-mappings")
def get_mappings(user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    seed_org(db, user["org"])
    db.commit()
    rows = db.execute("SELECT category_key,collection FROM category_mappings WHERE org=? "
                      "ORDER BY category_key,collection", (user["org"],))
    return [dict(r) for r in rows]


@router.put("/category-mappings/{key}")
def set_mapping(key: str, body: MappingUpdate, user=Depends(require(*MANAGERS)),
                db: sqlite3.Connection = Depends(get_db)):
    _check_collections(body.collections)
    seed_org(db, user["org"])
    _require_category(db, user["org"], key)
    db.execute("DELETE FROM category_mappings WHERE org=? AND category_key=?", (user["org"], key))
    unique = list(dict.fromkeys(body.collections))
    for collection in unique:
        db.execute("INSERT INTO category_mappings(org,category_key,collection) VALUES(?,?,?)",
                   (user["org"], key, collection))
    audit(db, user, f"updated guideline mapping {key}")
    db.commit()
    return {"category": key, "collections": unique}


@router.post("/guidelines")
async def add_guideline(collection: str = Form(...), source: str = Form(...), version: str = Form(""),
                        text: str = Form(""), url: str = Form(""), jurisdiction: str = Form(""),
                        effective_date: str = Form(""), section: str = Form(""),
                        file: UploadFile | None = File(None),
                        user=Depends(require(*MANAGERS)), db: sqlite3.Connection = Depends(get_db)):
    if collection not in COLLECTIONS:
        raise AppError(422, "Unknown collection")
    if file:
        pages = extract_pages(await file.read(), settings.max_upload_bytes)
    else:
        if len(text.encode("utf-8")) > settings.max_upload_bytes:
            raise AppError(413, "Guideline text is too large")
        pages = [(1, text)]
    count = 0
    for page, page_text in pages:
        for chunk in chunk_text(page_text):
            db.execute("""INSERT INTO guidelines(org,collection,source,version,page,text,url,jurisdiction,
                          effective_date,section,status) VALUES(?,?,?,?,?,?,?,?,?,?,'active')""",
                       (user["org"], collection, source[:250], version[:100], page, chunk, url[:1000],
                        jurisdiction[:200], effective_date[:40], section[:250]))
            count += 1
    if count == 0:
        raise AppError(422, "No text extracted")
    audit(db, user, f"import {source}")
    db.commit()
    return {"chunks": count}


@router.get("/guidelines")
def list_guidelines(q: str = "", user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    rows = [dict(r) for r in db.execute("SELECT * FROM guidelines WHERE org=?", (user["org"],))]
    return rank(q, rows, 50) if q else rows[:200]


@router.delete("/guidelines/{source:path}")
def delete_guideline(source: str, user=Depends(require(*MANAGERS)), db: sqlite3.Connection = Depends(get_db)):
    deleted = db.execute("DELETE FROM guidelines WHERE org=? AND source=?", (user["org"], source)).rowcount
    audit(db, user, f"delete source {source}")
    db.commit()
    return {"deleted": deleted}
