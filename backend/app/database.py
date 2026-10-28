"""SQLite access: schema, lightweight migrations, per-request connections, audit helper."""
from __future__ import annotations

import sqlite3
import time
from typing import Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, pw TEXT, role TEXT, org TEXT);
CREATE TABLE IF NOT EXISTS guidelines(
  id INTEGER PRIMARY KEY, org TEXT, collection TEXT, source TEXT, version TEXT, page INT, text TEXT,
  url TEXT DEFAULT '', jurisdiction TEXT DEFAULT '', effective_date TEXT DEFAULT '',
  section TEXT DEFAULT '', status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS contents(
  id INTEGER PRIMARY KEY, org TEXT, title TEXT, text TEXT, created REAL, created_by TEXT DEFAULT '',
  status TEXT DEFAULT 'needs_review', elements_json TEXT DEFAULT '[]', external_ai_used INTEGER DEFAULT 0,
  file_name TEXT DEFAULT '', mime_type TEXT DEFAULT '', file_blob BLOB);
CREATE TABLE IF NOT EXISTS findings(
  id INTEGER PRIMARY KEY, content_id INT, org TEXT, element TEXT, category TEXT, flag TEXT, method TEXT,
  explanation TEXT, evidence TEXT, suggestion TEXT, review_status TEXT DEFAULT 'open', created REAL,
  lens TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, finding_id INT, org TEXT, user TEXT, action TEXT, note TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS drafts(id INTEGER PRIMARY KEY, content_id INT, org TEXT, version INT, text TEXT, approved_by TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, org TEXT, user TEXT, event TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, org TEXT, key TEXT, name TEXT, description TEXT DEFAULT '',
  active INTEGER DEFAULT 1, UNIQUE(org,key));
CREATE TABLE IF NOT EXISTS category_mappings(
  id INTEGER PRIMARY KEY, org TEXT, category_key TEXT, collection TEXT, UNIQUE(org,category_key,collection));
CREATE TABLE IF NOT EXISTS content_elements(
  id INTEGER PRIMARY KEY, content_id INT, org TEXT, element_type TEXT, text TEXT DEFAULT '',
  description TEXT DEFAULT '', categories_json TEXT, page INT DEFAULT 1, bbox_json TEXT DEFAULT '',
  confidence REAL, extraction_method TEXT, created REAL);
CREATE TABLE IF NOT EXISTS review_assignments(
  id INTEGER PRIMARY KEY, content_id INT, org TEXT, assigned_to TEXT, assigned_by TEXT,
  status TEXT DEFAULT 'assigned', ts REAL);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, content_id INT, draft_id INT, org TEXT, approved_by TEXT,
  decision TEXT, note TEXT DEFAULT '', ts REAL);
CREATE TABLE IF NOT EXISTS corrections(
  id INTEGER PRIMARY KEY, org TEXT, category TEXT, original_text TEXT, corrected_text TEXT,
  source_finding INT, accepted_by TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS privacy_settings(
  org TEXT PRIMARY KEY, external_ai_allowed INTEGER DEFAULT 0, log_access_events INTEGER DEFAULT 1,
  allow_downloads INTEGER DEFAULT 0, retention_days TEXT DEFAULT '90', updated_by TEXT DEFAULT '',
  updated_at REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_guidelines_org ON guidelines(org, collection, status);
CREATE INDEX IF NOT EXISTS idx_contents_org ON contents(org);
CREATE INDEX IF NOT EXISTS idx_findings_content ON findings(content_id, org);
CREATE INDEX IF NOT EXISTS idx_elements_content ON content_elements(content_id, org);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit(org, id);
"""

# Columns added in later versions: (table, column, definition). Applied to older databases.
MIGRATIONS = [
    ("contents", "created_by", "TEXT DEFAULT ''"),
    ("contents", "status", "TEXT DEFAULT 'needs_review'"),
    ("contents", "elements_json", "TEXT DEFAULT '[]'"),
    ("contents", "external_ai_used", "INTEGER DEFAULT 0"),
    ("contents", "file_name", "TEXT DEFAULT ''"),
    ("contents", "mime_type", "TEXT DEFAULT ''"),
    ("contents", "file_blob", "BLOB"),
    ("findings", "lens", "TEXT DEFAULT ''"),
    ("guidelines", "url", "TEXT DEFAULT ''"),
    ("guidelines", "jurisdiction", "TEXT DEFAULT ''"),
    ("guidelines", "effective_date", "TEXT DEFAULT ''"),
    ("guidelines", "section", "TEXT DEFAULT ''"),
    ("guidelines", "status", "TEXT DEFAULT 'active'"),
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(
    settings.db_path,
    timeout=15,
    check_same_thread=False,
)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed. Handlers commit explicitly."""
    conn = connect()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit(db: sqlite3.Connection, user: dict, event: str) -> None:
    """Record an audit event inside the caller's transaction (the caller commits)."""
    db.execute("INSERT INTO audit(org,user,event,ts) VALUES(?,?,?,?)",
               (user["org"], user["email"], event[:1000], time.time()))


def privacy_for_org(db: sqlite3.Connection, org: str) -> dict:
    db.execute("INSERT OR IGNORE INTO privacy_settings(org) VALUES(?)", (org,))
    row = db.execute("SELECT * FROM privacy_settings WHERE org=?", (org,)).fetchone()
    return dict(row)
