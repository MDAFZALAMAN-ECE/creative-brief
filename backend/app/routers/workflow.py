"""Finding review decisions, assignments, status changes and approvals."""
import sqlite3
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..database import audit, get_db
from ..errors import AppError
from ..security import current_user, require
from .contents import REVIEWERS, get_owned

router = APIRouter(prefix="/api/v1", tags=["workflow"])
REVIEW_ACTIONS = {"accept", "reject", "false_positive", "dismiss", "resolve", "reopen", "request_evidence", "comment"}
STATUS_FOR_ACTION = {"reopen": "open", "request_evidence": "needs_evidence"}


class ReviewAction(BaseModel):
    action: str
    note: str = ""
    suggestion: str | None = None


class Assignment(BaseModel):
    assigned_to: str


class StatusUpdate(BaseModel):
    status: str
    note: str = ""


class ApprovalDecision(BaseModel):
    decision: str = "approved"
    note: str = ""


@router.post("/findings/{fid}/review")
def review_finding(fid: int, body: ReviewAction, user=Depends(current_user),
                   db: sqlite3.Connection = Depends(get_db)):
    if body.action not in REVIEW_ACTIONS:
        raise AppError(422, "Bad action")
    if user["role"] == "creator" and body.action != "comment":
        raise AppError(403, "Creators may comment; reviewers/managers make review decisions")
    if body.action == "comment" and not body.note.strip():
        raise AppError(422, "A comment is required")
    finding = db.execute("SELECT element,category,suggestion FROM findings WHERE id=? AND org=?",
                         (fid, user["org"])).fetchone()
    if not finding:
        raise AppError(404, "Not found")
    status = None
    if body.action != "comment":
        status = STATUS_FOR_ACTION.get(body.action, body.action)
        db.execute("UPDATE findings SET review_status=?, suggestion=COALESCE(NULLIF(?,''),suggestion) "
                   "WHERE id=? AND org=?", (status, body.suggestion, fid, user["org"]))
        if body.action == "accept":
            correction = (body.suggestion or finding["suggestion"] or "").strip()
            if correction and correction != finding["element"]:
                db.execute("""INSERT INTO corrections(org,category,original_text,corrected_text,source_finding,
                              accepted_by,ts) VALUES(?,?,?,?,?,?,?)""",
                           (user["org"], finding["category"], finding["element"], correction, fid,
                            user["email"], time.time()))
    db.execute("INSERT INTO reviews(finding_id,org,user,action,note,ts) VALUES(?,?,?,?,?,?)",
               (fid, user["org"], user["email"], body.action, body.note, time.time()))
    db.commit()
    return {"status": status or "commented"}


@router.get("/findings/{fid}/history")
def finding_history(fid: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    if not db.execute("SELECT 1 FROM findings WHERE id=? AND org=?", (fid, user["org"])).fetchone():
        raise AppError(404, "Not found")
    rows = db.execute("SELECT * FROM reviews WHERE finding_id=? AND org=? ORDER BY id", (fid, user["org"]))
    return [dict(r) for r in rows]


@router.post("/contents/{cid}/assign")
def assign(cid: int, body: Assignment, user=Depends(require("admin", "manager")),
           db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    assignee = body.assigned_to.strip().lower()
    target = db.execute("SELECT role FROM users WHERE email=? AND org=?", (assignee, user["org"])).fetchone()
    if not target or target["role"] not in {"reviewer", "manager", "admin"}:
        raise AppError(422, "Assignee must be a reviewer, manager, or admin in this organization")
    db.execute("INSERT INTO review_assignments(content_id,org,assigned_to,assigned_by,status,ts) VALUES(?,?,?,?,?,?)",
               (cid, user["org"], assignee, user["email"], "assigned", time.time()))
    audit(db, user, f"assigned content {cid} to {assignee}")
    db.commit()
    return {"assigned_to": assignee, "status": "assigned"}


@router.get("/contents/{cid}/assignments")
def list_assignments(cid: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    rows = db.execute("SELECT * FROM review_assignments WHERE content_id=? AND org=? ORDER BY id DESC",
                      (cid, user["org"]))
    return [dict(r) for r in rows]


@router.put("/contents/{cid}/status")
def update_status(cid: int, body: StatusUpdate, user=Depends(require(*REVIEWERS)),
                  db: sqlite3.Connection = Depends(get_db)):
    if body.status not in {"needs_review", "in_review", "changes_requested"}:
        raise AppError(422, "Status must be needs_review, in_review, or changes_requested; "
                            "approval uses the approval endpoint")
    get_owned(db, cid, user)
    db.execute("UPDATE contents SET status=? WHERE id=? AND org=?", (body.status, cid, user["org"]))
    audit(db, user, f"content {cid} status={body.status}; note={body.note[:250]}")
    db.commit()
    return {"content_id": cid, "status": body.status, "updated_by": user["email"]}


@router.post("/contents/{cid}/approve")
def approve(cid: int, body: ApprovalDecision = ApprovalDecision(), user=Depends(require(*REVIEWERS)),
            db: sqlite3.Connection = Depends(get_db)):
    if body.decision not in {"approved", "rejected", "needs_changes"}:
        raise AppError(422, "Invalid approval decision")
    get_owned(db, cid, user)
    db.execute("INSERT INTO approvals(content_id,draft_id,org,approved_by,decision,note,ts) VALUES(?,NULL,?,?,?,?,?)",
               (cid, user["org"], user["email"], body.decision, body.note[:2000], time.time()))
    db.execute("UPDATE contents SET status=? WHERE id=? AND org=?",
               ("approved" if body.decision == "approved" else "changes_requested", cid, user["org"]))
    audit(db, user, f"{body.decision} creative {cid}")
    db.commit()
    return {"decision": body.decision, "approved_by": user["email"], "content_id": cid}


@router.get("/contents/{cid}/approvals")
def list_approvals(cid: int, user=Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    get_owned(db, cid, user)
    rows = db.execute("SELECT * FROM approvals WHERE content_id=? AND org=? ORDER BY id DESC", (cid, user["org"]))
    return [dict(r) for r in rows]
