"""Privacy settings, audit log, correction library, governance dashboard and health."""
import importlib.util
import sqlite3
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import settings
from ..database import audit, get_db, privacy_for_org
from ..errors import AppError
from ..retrieval import semantic_available
from ..security import current_user, require

router = APIRouter(prefix="/api/v1", tags=["governance"])
RETENTION_CHOICES = {"30", "90", "180", "365", "manual"}
PUBLIC_PRIVACY_FIELDS = ("org", "external_ai_allowed", "log_access_events", "allow_downloads",
                         "retention_days", "updated_at")


class PrivacyUpdate(BaseModel):
    external_ai_allowed: bool = False
    log_access_events: bool = True
    allow_downloads: bool = False
    retention_days: str = "90"


def _public_privacy(db, org: str) -> dict:
    row = privacy_for_org(db, org)
    db.commit()
    return {k: row[k] for k in PUBLIC_PRIVACY_FIELDS}


@router.get("/privacy/settings")
def get_privacy(user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return _public_privacy(db, user["org"])


@router.put("/privacy/settings")
def update_privacy(body: PrivacyUpdate, user=Depends(require("admin", "manager")),
                   db: sqlite3.Connection = Depends(get_db)):
    if body.retention_days not in RETENTION_CHOICES:
        raise AppError(422, "Invalid retention period")
    db.execute("""INSERT INTO privacy_settings(org,external_ai_allowed,log_access_events,allow_downloads,
                  retention_days,updated_by,updated_at) VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(org) DO UPDATE SET external_ai_allowed=excluded.external_ai_allowed,
                  log_access_events=excluded.log_access_events, allow_downloads=excluded.allow_downloads,
                  retention_days=excluded.retention_days, updated_by=excluded.updated_by,
                  updated_at=excluded.updated_at""",
               (user["org"], int(body.external_ai_allowed), int(body.log_access_events), int(body.allow_downloads),
                body.retention_days, user["email"], time.time()))
    audit(db, user, "updated privacy settings")
    db.commit()
    return _public_privacy(db, user["org"])


@router.get("/audit")
def list_audit(limit: int = 50, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    limit = max(1, min(int(limit), 200))
    rows = db.execute("SELECT id,user,event,ts FROM audit WHERE org=? ORDER BY id DESC LIMIT ?", (user["org"], limit))
    return [dict(r) for r in rows]


@router.get("/corrections")
def correction_library(q: str = "", user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    if q.strip():
        like = f"%{q.strip()[:150]}%"
        rows = db.execute("SELECT * FROM corrections WHERE org=? AND (original_text LIKE ? OR corrected_text LIKE ? "
                          "OR category LIKE ?) ORDER BY id DESC LIMIT 200", (user["org"], like, like, like))
    else:
        rows = db.execute("SELECT * FROM corrections WHERE org=? ORDER BY id DESC LIMIT 200", (user["org"],))
    return [dict(r) for r in rows]


@router.get("/governance")
def governance(user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    def q(sql: str) -> list[dict]:
        return [dict(r) for r in db.execute(sql, (user["org"],))]
    return {
        "by_flag": q("SELECT flag,COUNT(*) n FROM findings WHERE org=? GROUP BY flag"),
        "by_category": q("SELECT category,COUNT(*) n FROM findings WHERE org=? GROUP BY category"),
        "by_review": q("SELECT review_status,COUNT(*) n FROM findings WHERE org=? GROUP BY review_status"),
        "repeat_elements": q("SELECT element,COUNT(*) n FROM findings WHERE org=? GROUP BY element "
                             "HAVING n>1 ORDER BY n DESC LIMIT 10"),
        "uncertainty_signals": q("SELECT category,COUNT(*) n FROM findings WHERE org=? AND flag='ORANGE' "
                                 "GROUP BY category HAVING n>=2 ORDER BY n DESC"),
        "accepted_corrections": q("SELECT category,COUNT(*) n FROM corrections WHERE org=? GROUP BY category"),
        "guideline_sources": q("SELECT collection,COUNT(DISTINCT source) n FROM guidelines WHERE org=? "
                               "GROUP BY collection"),
        "audit": q("SELECT user,event,ts FROM audit WHERE org=? ORDER BY id DESC LIMIT 25"),
    }


@router.get("/health")
def health():
    def has(module: str) -> bool:
        return importlib.util.find_spec(module) is not None
    return {"ok": True, "capabilities": {
        "keyword_retrieval": True, "ocr": has("pytesseract"), "pdf": has("fitz"), "docx": has("docx"),
        "groq": settings.groq_ready, "gemini": settings.gemini_ready,
        "gemini_vision_configured": settings.gemini_ready,
        "semantic_embeddings": semantic_available(),
        "semantic_search_requested": settings.semantic_search,
        "sentence_transformers_installed": has("sentence_transformers"),
        "element_breakdown": True, "category_guideline_mapping": True}}
