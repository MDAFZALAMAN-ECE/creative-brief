"""Guideline retrieval: lexical matching, with optional local semantic search (sentence-transformers).

`sentence-transformers` is an OPTIONAL dependency. It is imported dynamically so editors such as
VS Code/Pylance do not report "Import could not be resolved" when it is not installed, and so the
app keeps working (lexical retrieval) when it is missing.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import logging
import re
from typing import Any, Iterable

from .config import settings

log = logging.getLogger("creative_brief.retrieval")
_TOKEN = re.compile(r"[a-z0-9]{3,}")
SEMANTIC_MIN_SCORE = 0.15

_model: Any = None
_model_name: str | None = None
_semantic_broken = False
_vectors: dict[tuple[str, str], Any] = {}


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def lexical_rank(query: str, rows: Iterable[dict], k: int) -> list[dict]:
    qt = tokens(query)
    if not qt:
        return []
    scored = [(len(qt & tokens(r["text"])) / len(qt), r) for r in rows]
    scored.sort(key=lambda x: -x[0])
    return [r for score, r in scored if score > 0][:k]


def semantic_available() -> bool:
    if not settings.semantic_search or _semantic_broken:
        return False
    return (importlib.util.find_spec("sentence_transformers") is not None
            and importlib.util.find_spec("numpy") is not None)


def _embed(texts: list[str]) -> list[Any]:
    """Embed texts, caching one vector per distinct text so guidelines are encoded only once."""
    global _model, _model_name
    st = importlib.import_module("sentence_transformers")
    if _model is None or _model_name != settings.embedding_model:
        _model = st.SentenceTransformer(settings.embedding_model)
        _model_name = settings.embedding_model
    keys = [(settings.embedding_model, hashlib.sha1(t.encode("utf-8")).hexdigest()) for t in texts]
    missing = [(k, t) for k, t in zip(keys, texts) if k not in _vectors]
    if missing:
        vecs = _model.encode([t for _, t in missing], normalize_embeddings=True)
        for (k, _), vec in zip(missing, vecs):
            _vectors[k] = vec
    return [_vectors[k] for k in keys]


def semantic_rank(query: str, rows: list[dict], k: int) -> list[dict] | None:
    """Return ranked rows, or None if semantic search is unavailable/failed (caller falls back)."""
    global _semantic_broken
    if not semantic_available():
        return None
    try:
        np = importlib.import_module("numpy")
        vectors = _embed([query] + [str(r["text"]) for r in rows])
        q, docs = vectors[0], vectors[1:]
        scored = sorted(((float(np.dot(v, q)), r) for v, r in zip(docs, rows)), key=lambda x: -x[0])
        return [r for score, r in scored[:k] if score > SEMANTIC_MIN_SCORE]
    except Exception as exc:                                  # bad model name, no internet, torch error...
        _semantic_broken = True
        log.warning("Semantic search disabled, falling back to keyword retrieval: %s", exc)
        return None


def rank(query: str, rows: list[dict], k: int = 3) -> list[dict]:
    if not rows or not (query or "").strip():
        return []
    semantic = semantic_rank(query, rows, k)
    return semantic if semantic is not None else lexical_rank(query, rows, k)
