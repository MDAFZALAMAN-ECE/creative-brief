"""Pure-logic tests (no web framework needed)."""
import sqlite3

from app import database
from app.categories import category_for, seed_org
from app.evaluation import evaluate_text, run_evaluation
from app.extraction import chunk_text, sniff, split_elements
from app.retrieval import lexical_rank, rank, tokens


def row(collection, text, source="src"):
    return {"collection": collection, "text": text, "source": source, "version": "1", "page": 1}


def test_sniff_detects_by_content():
    assert sniff(b"%PDF-1.7 ...") == "pdf"
    assert sniff(b"\x89PNG\r\n\x1a\n....") == "png"
    assert sniff(b"\xff\xd8\xff\xe0....") == "jpeg"
    assert sniff(b"hello") == "other"


def test_chunking_respects_size_and_keeps_text():
    long_para = " ".join(f"Sentence number {i} is here." for i in range(80))
    chunks = chunk_text(long_para + "\n\nShort second paragraph.", size=300)
    assert len(chunks) > 3
    assert all(len(c) <= 330 for c in chunks)
    assert "Short second paragraph." in chunks[-1]


def test_split_elements_one_per_line():
    els = split_elements("Buy now\n\nBest price guaranteed\n")
    assert [e["text"] for e in els] == ["Buy now", "Best price guaranteed"]
    assert "promotional_claims" in els[1]["categories"]


def test_category_for_defaults_to_other():
    assert category_for("hello world") == ["other"]
    assert "visual_consistency" in category_for("", element_type="logo")


def test_lexical_rank_orders_by_overlap():
    rows = [row("brand_guidelines", "our tone is calm and reassuring"),
            row("brand_guidelines", "colour palette uses blue")]
    assert lexical_rank("calm reassuring tone", rows, 1)[0]["text"].startswith("our tone")
    assert rank("", rows) == []
    assert rank("zzzzzz", rows) == []


def test_terminology_rule_suggests_replacement():
    rows = [row("terminology_tone", "avoid: cheap -> affordable")]
    hits = evaluate_text("Our cheap plans start today.", rows)
    assert hits[0].flag == "RED" and "affordable" in hits[0].suggestion


def test_forbidden_phrase_rule():
    hits = evaluate_text("This is a miracle product.", [row("custom", "forbid: miracle")], allow_claims=False)
    assert [h.method for h in hits] == ["explicit_forbidden_phrase_rule"]


def test_claim_without_evidence_is_orange_not_green():
    hits = evaluate_text("The best product ever.", [row("approved_claims", "unrelated words about shipping")])
    assert hits and hits[0].flag == "ORANGE"


def test_approved_claim_match_is_green():
    approved = [row("approved_claims", "clinically proven to improve skin hydration")]
    hits = evaluate_text("Clinically proven to improve skin hydration.", approved)
    assert hits[0].flag == "GREEN"


def test_claim_made_only_of_symbols_does_not_crash():
    # Regression: 100% has no 3+ char tokens -> used to divide by zero when evidence existed.
    approved = [row("approved_claims", "100 percent satisfaction")]
    assert evaluate_text("100%!", approved)[0].flag in {"ORANGE", "GREEN"}


def test_full_evaluation_pipeline():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(database.SCHEMA)
    seed_org(conn, "acme")
    conn.execute("INSERT INTO guidelines(org,collection,source,version,page,text,status) "
                 "VALUES('acme','terminology_tone','Glossary','1',1,'avoid: cheap -> affordable','active')")
    conn.execute("INSERT INTO contents(org,title,text,created,elements_json) VALUES('acme','Ad','Cheap deals',0,'[]')")
    content = conn.execute("SELECT * FROM contents").fetchone()
    user = {"org": "acme", "email": "a@acme.com", "role": "admin"}
    result = run_evaluation(conn, user, content, use_ai=False, consent=False)
    assert result["findings_created"] >= 1 and result["rules_only"] is True
    flags = {r["flag"] for r in conn.execute("SELECT flag FROM findings")}
    assert "RED" in flags


def test_symbol_claims_are_detected():
    # Regression: the original \b-based regex never matched "100%" or "#1".
    assert "promotional_claims" in category_for("We are #1 in India")
    assert "promotional_claims" in category_for("100% natural")
    assert evaluate_text("We are #1 in India.", [row("approved_claims", "something else")])[0].flag == "ORANGE"
