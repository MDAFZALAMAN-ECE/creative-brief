"""Category registry, guideline collections and keyword-based category detection."""
from __future__ import annotations

import re
import sqlite3

COLLECTIONS = ["official_regulations", "brand_guidelines", "approved_claims", "terminology_tone",
               "visual_identity", "marketing_research", "accessibility", "custom"]
CLAIM_COLLECTIONS = {"approved_claims", "official_regulations", "marketing_research"}
VISUAL_TYPES = {"image", "logo", "color", "colour", "layout", "visual"}

CATEGORY_DEFS = [
    ("tone", "Tone", "Voice, formality, personality, and writing style."),
    ("terminology", "Terminology", "Preferred terms, prohibited phrases, and glossary."),
    ("messaging", "Messaging", "Positioning, audience, narrative, and message consistency."),
    ("visual_consistency", "Visual consistency", "Logo, colors, typography, imagery, and layout."),
    ("accessibility", "Accessibility", "Contrast, legibility, alt text, and inclusive communication."),
    ("promotional_claims", "Promotional claims", "Product promises, guarantees, comparative and health claims."),
    ("approved_facts", "Approved facts", "Verified brand facts, product attributes, and approved claims."),
    ("official_regulations", "Official regulations", "Regulatory or advertising requirements."),
    ("marketing_research", "Marketing research", "Research-based creative and marketing considerations."),
    ("other", "Other / needs review", "Elements that could not be confidently categorized."),
]
CATEGORY_KEYS = {key for key, _, _ in CATEGORY_DEFS}

DEFAULT_MAPPINGS = {
    "tone": ["brand_guidelines", "terminology_tone"],
    "terminology": ["terminology_tone", "brand_guidelines"],
    "messaging": ["brand_guidelines", "approved_claims", "marketing_research"],
    "visual_consistency": ["visual_identity", "brand_guidelines", "accessibility"],
    "accessibility": ["accessibility", "visual_identity"],
    "promotional_claims": ["approved_claims", "official_regulations", "marketing_research"],
    "approved_facts": ["approved_claims", "brand_guidelines"],
    "official_regulations": ["official_regulations"],
    "marketing_research": ["marketing_research"],
    "other": ["custom"],
}

_CLAIM_WORDS = re.compile(r"(?<!\w)(best|#1|number one|guarantee|guaranteed|100\s?%|cure|miracle|clinically proven|"
                          r"risk[- ]free|lose \d+|increase|reduce|fastest|only)(?!\w)")
_MESSAGING_WORDS = re.compile(r"\b(our|we|brand|mission|designed for|made for|because|discover|experience)\b")
_TONE_WORDS = re.compile(r"\b(cheap|affordable|premium|luxury|friendly|professional|awesome|amazing)\b")
_VISUAL_WORDS = re.compile(r"\b(logo|font|color|colour|contrast|alt text|readable|legible)\b")


def seed_org(db: sqlite3.Connection, org: str) -> None:
    """Seed the default registry once per organization; never resurrect mappings a user removed."""
    if db.execute("SELECT 1 FROM categories WHERE org=? LIMIT 1", (org,)).fetchone():
        return
    for key, name, desc in CATEGORY_DEFS:
        db.execute("INSERT OR IGNORE INTO categories(org,key,name,description,active) VALUES(?,?,?,?,1)",
                   (org, key, name, desc))
    for key, collections in DEFAULT_MAPPINGS.items():
        for collection in collections:
            db.execute("INSERT OR IGNORE INTO category_mappings(org,category_key,collection) VALUES(?,?,?)",
                       (org, key, collection))


def category_for(text: str, element_type: str = "text", description: str = "") -> list[str]:
    q = f"{text} {description}".lower()
    cats: list[str] = []
    if element_type in VISUAL_TYPES | {"visual"}:
        cats.append("visual_consistency")
    if _CLAIM_WORDS.search(q):
        cats.append("promotional_claims")
    if _MESSAGING_WORDS.search(q):
        cats.append("messaging")
    if _TONE_WORDS.search(q):
        cats.extend(["terminology", "tone"])
    if _VISUAL_WORDS.search(q):
        cats.extend(["visual_consistency", "accessibility"])
    return list(dict.fromkeys(cats)) or ["other"]


def mapping_for_org(db: sqlite3.Connection, org: str) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for row in db.execute("SELECT category_key, collection FROM category_mappings WHERE org=?", (org,)):
        mapping.setdefault(row["category_key"], set()).add(row["collection"])
    return mapping
