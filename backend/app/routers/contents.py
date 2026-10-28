"""Creatives: upload + element extraction, evaluation, findings and file access."""
import json
import sqlite3
import time

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel

from .. import ai
from ..categories import seed_org
from ..config import settings
from ..database import audit, get_db, privacy_for_org
from ..errors import AppError
from ..evaluation import run_evaluation
from ..extraction import extract_pages, is_image, sniff, split_elements
from ..security import current_user, require

router = APIRouter(prefix="/api/v1", tags=["contents"])
EDITORS = ("admin", "manager", "creator")
REVIEWERS = ("admin", "manager", "reviewer")


def get_owned(db: sqlite3.Connection, cid: int, user: dict) -> sqlite3.Row:
    row = db.execute("SELECT * FROM contents WHERE id=? AND org=?", (cid, user["org"])).fetchone()
    if not row:
        raise AppError(404, "Not found")
    return row


@router.post("/contents")
async def submit(title: str = Form(...), text: str = Form(""), external_ai_consent: bool = Form(False),
                 file: UploadFile | None = File(None), user=Depends(require(*EDITORS)),
                 db: sqlite3.Connection = Depends(get_db)):
    data = await file.read() if file else None
    if data is None and len(text.encode("utf-8")) > settings.max_upload_bytes:
        raise AppError(413, "Text submission is too large")
    pages = extract_pages(data, settings.max_upload_bytes) if data is not None else [(1, text)]
    extracted = "\n".join(t for _, t in pages).strip()
    if not extracted and not data:
        raise AppError(422, "Empty content")

    elements = [dict(el, page=page) for page, page_text in pages for el in split_elements(page_text, page)]
    vision_used = False
    if data and is_image(data) and external_ai_consent and privacy_for_org(db, user["org"])["external_ai_allowed"]:
        seen = {(e["element_type"], e["text"].strip().lower(), e["description"].strip().lower()) for e in elements}
        for el in ai.vision_elements(data) or []:
            key = (el["element_type"], el["text"].strip().lower(), el["description"].strip().lower())
            if key not in seen:
                elements.append(el)
                seen.add(key)
                vision_used = True
    if not elements and extracted:
        elements = split_elements(extracted)

    seed_org(db, user["org"])
    now = time.time()
    cid = db.execute(
        """INSERT INTO contents(org,title,text,created,created_by,status,elements_json,external_ai_used,
           file_name,mime_type,file_blob) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (user["org"], title.strip()[:250], extracted, now, user["email"], "needs_review", json.dumps(elements),
         int(vision_used), file.filename if file else "",
         (file.content_type if file else "text/plain") or "application/octet-stream",
         sqlite3.Binary(data) if data else None)).lastrowid
    for el in elements:
        db.execute("""INSERT INTO content_elements(content_id,org,element_type,text,description,categories_json,
                      page,bbox_json,confidence,extraction_method,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (cid, user["org"], el.get("element_type", "other"), el.get("text", ""), el.get("description", ""),
                    json.dumps(el.get("categories", ["other"])), el.get("page", 1),
                    json.dumps(el["bbox"]) if el.get("bbox") else "", el.get("confidence"),
                    el.get("method", "unknown"), now))
    audit(db, user, f"content {cid}; elements={len(elements)}; vision={vision_used}")
    db.commit()
    return {"id": cid, "elements_detected": len(elements), "vision_analysis_used": vision_used,
            "external_ai_used": vision_used,
            "message": "Review extracted elements before relying on the analysis."}


@router.get("/contents")
def list_contents(user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("SELECT id,title,created,created_by,status,external_ai_used FROM contents "
                      "WHERE org=? ORDER BY id DESC", (user["org"],))
    return [dict(r) for r in rows]


@router.get("/contents/{cid}/original")
def get_original(cid: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    row = get_owned(db, cid, user)
    if not row["file_blob"]:
        return Response(row["text"], media_type="text/plain; charset=utf-8")
    data = bytes(row["file_blob"])
    # Never trust the browser-supplied MIME type; only render known-safe types inline.
    mime = {"png": "image/png", "jpeg": "image/jpeg", "pdf": "application/pdf"}.get(sniff(data))
    return Response(data, media_type=mime or "application/octet-stream",
                    headers={"Content-Disposition": "inline" if mime else "attachment",
                             "X-Content-Type-Options": "nosniff"})


@router.get("/contents/{cid}/elements")
def get_elements(cid: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    out = []
    for r in db.execute("SELECT * FROM content_elements WHERE content_id=? AND org=? ORDER BY id", (cid, user["org"])):
        row = dict(r)
        row["categories"] = json.loads(row.pop("categories_json") or "[]")
        bbox = row.pop("bbox_json")
        row["bbox"] = json.loads(bbox) if bbox else None
        out.append(row)
    return out


class ElementEdit(BaseModel):
    text: str = ""
    description: str = ""
    categories: list[str] = []


@router.put("/contents/{cid}/elements/{eid}")
def edit_element(cid: int, eid: int, body: ElementEdit, user=Depends(require(*EDITORS)),
                 db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    seed_org(db, user["org"])
    valid = {r["key"] for r in db.execute("SELECT key FROM categories WHERE org=? AND active=1", (user["org"],))}
    if any(k not in valid for k in body.categories):
        raise AppError(422, "Unknown or inactive category")
    if not db.execute("SELECT 1 FROM content_elements WHERE id=? AND content_id=? AND org=?",
                      (eid, cid, user["org"])).fetchone():
        raise AppError(404, "Element not found")
    db.execute("UPDATE content_elements SET text=?,description=?,categories_json=? WHERE id=?",
               (body.text[:5000], body.description[:2000], json.dumps(body.categories or ["other"]), eid))
    # Keep the denormalised snapshot used by evaluation in sync with the edited rows.
    snapshot = [{"element_type": e["element_type"], "text": e["text"], "description": e["description"],
                 "categories": json.loads(e["categories_json"] or "[]"), "page": e["page"],
                 "bbox": json.loads(e["bbox_json"]) if e["bbox_json"] else None,
                 "confidence": e["confidence"], "method": e["extraction_method"]}
                for e in db.execute("SELECT * FROM content_elements WHERE content_id=? AND org=? ORDER BY id",
                                    (cid, user["org"]))]
    db.execute("UPDATE contents SET elements_json=? WHERE id=? AND org=?", (json.dumps(snapshot), cid, user["org"]))
    audit(db, user, f"edited element {eid} on content {cid}")
    db.commit()
    return {"updated": True}


@router.post("/contents/{cid}/evaluate")
def evaluate(cid: int, use_ai: bool = False, external_ai_consent: bool = False,
             user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return run_evaluation(db, user, get_owned(db, cid, user), use_ai, external_ai_consent)


@router.get("/contents/{cid}/findings")
def list_findings(cid: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    return [dict(r) for r in db.execute("SELECT * FROM findings WHERE content_id=? AND org=? ORDER BY id",
                                        (cid, user["org"]))]


@router.delete("/contents/{cid}")
def delete_content(cid: int, user=Depends(require("admin", "manager")), db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    org = user["org"]
    ids = [r["id"] for r in db.execute("SELECT id FROM findings WHERE content_id=? AND org=?", (cid, org))]
    for fid in ids:
        db.execute("DELETE FROM reviews WHERE finding_id=? AND org=?", (fid, org))
        db.execute("DELETE FROM corrections WHERE source_finding=? AND org=?", (fid, org))
    for table in ("findings", "drafts", "content_elements", "review_assignments", "approvals"):
        db.execute(f"DELETE FROM {table} WHERE content_id=? AND org=?", (cid, org))
    db.execute("DELETE FROM contents WHERE id=? AND org=?", (cid, org))
    audit(db, user, f"delete {cid}")
    db.commit()
    return {"deleted": True}
