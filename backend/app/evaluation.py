"""Evaluation pipeline: deterministic rule checks + optional evidence-grounded AI review.

Each guideline collection is its own evaluation "lens"; no source silently overrides another.
"No finding" never proves compliance, and flags are screening states, not legal determinations.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import NamedTuple

from . import ai
from .categories import (CATEGORY_DEFS, CLAIM_COLLECTIONS, DEFAULT_MAPPINGS, VISUAL_TYPES, category_for,
                         mapping_for_org, seed_org)
from .config import settings
from .database import audit, privacy_for_org
from .extraction import split_elements
from .retrieval import rank, tokens

# Lookarounds instead of \b: \b never matches next to symbols, so "100%" and "#1" were silently missed.
CLAIM = re.compile(r"(?<!\w)(best|#1|number one|guaranteed?|100\s?%|cure[sd]?|miracle|clinically proven|"
                   r"risk[- ]free|healthy|pure|natural)(?!\w)", re.I)
AVOID = re.compile(r"avoid:\s*(.+?)\s*(?:->|=>)\s*(.+)", re.I)
FORBID = re.compile(r"(?:forbid|must_not|prohibited):\s*(.+)", re.I)
APPROVED_CLAIM_OVERLAP = 0.6


class Hit(NamedTuple):
    element: str
    category: str
    flag: str
    method: str
    explanation: str
    evidence: list
    suggestion: str


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 3]


def evaluate_text(text: str, rows: list[dict], allow_claims: bool = True) -> list[Hit]:
    """Explicit glossary / forbidden-phrase / approved-claim checks against one collection's rows."""
    avoid = [(m.group(1).strip(), m.group(2).strip(), r) for r in rows if r["collection"] == "terminology_tone"
             for line in r["text"].splitlines() if (m := AVOID.search(line))]
    forbidden = [(m.group(1).strip(), r) for r in rows for line in r["text"].splitlines() if (m := FORBID.search(line))]
    approved = [r for r in rows if r["collection"] == "approved_claims"]
    regulatory = [r for r in rows if r["collection"] in ("official_regulations", "marketing_research")]
    hits: list[Hit] = []
    for s in _sentences(text):
        low = s.lower()
        for bad, good, r in avoid:
            if bad.lower() in low:
                hits.append(Hit(s, "terminology", "RED", "exact_terminology_rule",
                                f"Uses '{bad}', which the glossary asks to avoid.", [r],
                                re.sub(re.escape(bad), good, s, flags=re.I)))
        for bad, r in forbidden:
            if bad and bad.lower() in low:
                hits.append(Hit(s, "custom", "RED", "explicit_forbidden_phrase_rule",
                                f"Contains '{bad}', which an imported guideline explicitly marks as prohibited.",
                                [r], ""))
        if allow_claims and CLAIM.search(s):
            match = rank(s, approved, 1)
            if match and len(tokens(s) & tokens(match[0]["text"])) / max(len(tokens(s)), 1) > APPROVED_CLAIM_OVERLAP:
                hits.append(Hit(s, "promotional_claims", "GREEN", "approved_claim_match",
                                "Matches an approved claim.", match, ""))
            else:
                ev = rank(s, regulatory, 3)
                why = ("Promotional claim with possibly relevant guideline text; a human must verify." if ev else
                       "Promotional claim with NO supporting evidence in the knowledge base - cannot be verified.")
                hits.append(Hit(s, "promotional_claims", "ORANGE", "claim_needs_human_review", why, ev, ""))
    return hits


def _evidence_payload(rows: list[dict]) -> list[dict]:
    return [{"source": e["source"], "version": e["version"], "page": e["page"], "collection": e["collection"],
             "section": e.get("section", ""), "url": e.get("url", ""),
             "jurisdiction": e.get("jurisdiction", ""), "text": e["text"][:400]} for e in rows]


def run_evaluation(db: sqlite3.Connection, user: dict, content: sqlite3.Row,
                   use_ai: bool, consent: bool) -> dict:
    org, cid = user["org"], content["id"]
    guideline_rows = [dict(r) for r in db.execute("SELECT * FROM guidelines WHERE org=? AND status='active'", (org,))]
    seed_org(db, org)
    mapping = mapping_for_org(db, org)
    elements = json.loads(content["elements_json"] or "[]") or split_elements(content["text"])
    privacy = privacy_for_org(db, org)
    can_use_ai = bool(use_ai and consent and privacy["external_ai_allowed"] and settings.hosted_ai_ready)

    # Reviewer decisions are kept; only unreviewed findings are regenerated.
    db.execute("DELETE FROM findings WHERE content_id=? AND org=? AND review_status IN ('open','needs_evidence')",
               (cid, org))
    created = 0
    ai_reviews = 0

    def save(element, category, flag, method, why, evidence, suggestion, lens):
        nonlocal created
        db.execute("""INSERT INTO findings(content_id,org,element,category,flag,method,explanation,evidence,
                      suggestion,created,lens) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (cid, org, element, category, flag, method, why,
                    json.dumps(_evidence_payload(evidence)), suggestion, time.time(), lens))
        created += 1

    for el in elements:
        text = (el.get("text") or "").strip()
        desc = (el.get("description") or "").strip()
        etype = el.get("element_type", "text")
        categories = el.get("categories") or category_for(text, etype, desc)
        lenses: set[str] = set()
        for cat in categories:
            lenses.update(mapping.get(cat, DEFAULT_MAPPINGS.get(cat, ["custom"])))
        is_visual = etype in VISUAL_TYPES
        if is_visual:
            lenses.update(mapping.get("visual_consistency", DEFAULT_MAPPINGS["visual_consistency"]))

        for collection in sorted(lenses):
            rows = [g for g in guideline_rows if g["collection"] == collection]
            if not rows:
                if text and collection in CLAIM_COLLECTIONS and CLAIM.search(text):
                    save(text, "promotional_claims", "ORANGE", "claim_no_evidence",
                         f"NO supporting evidence in the {collection} collection; this claim cannot be verified "
                         "against this independent lens.", [], "", collection)
                continue
            if text:
                for h in evaluate_text(text, rows, allow_claims=collection in CLAIM_COLLECTIONS):
                    save(h.element, h.category, h.flag, h.method, h.explanation, h.evidence, h.suggestion, collection)
            evidence = rank(f"{text} {desc}".strip() or etype, rows, 4)
            if can_use_ai and evidence:
                result = ai.evaluate_element({"text": text, "description": desc, "element_type": etype},
                                             categories, evidence)
                if result:
                    ai_reviews += 1
                    save(text or desc or etype, result["category"], result["flag"], result["method"],
                         result["explanation"], evidence, result["suggestion"], collection)
            elif not text and is_visual and evidence:
                save(desc or etype, "visual_consistency", "ORANGE", "visual_guideline_context",
                     "Related visual guideline material was retrieved, but this visual check requires human "
                     "verification or a configured AI model.", evidence, "", collection)

    external_used = ai_reviews > 0
    if external_used:
        db.execute("UPDATE contents SET external_ai_used=1 WHERE id=? AND org=?", (cid, org))
    audit(db, user, f"evaluate {cid}; findings={created}; ai_reviews={ai_reviews}; external_ai={external_used}")
    db.commit()
    return {"rules_only": ai_reviews == 0, "ai_reviews_completed": ai_reviews, "external_ai_used": external_used,
            "knowledge_base_chunks": len(guideline_rows), "elements_evaluated": len(elements),
            "findings_created": created,
            "message": "Each collection is evaluated independently. No finding means no configured rule matched; "
                       "it does not prove compliance."}
