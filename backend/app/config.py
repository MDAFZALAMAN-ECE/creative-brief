"""Configuration: reads backend/.env (if present) and the process environment."""
from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("creative_brief")

BASE_DIR = Path(__file__).resolve().parent.parent          # .../backend
PROJECT_DIR = BASE_DIR.parent                               # project root
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"
PLACEHOLDER_SECRETS = {"", "replace-with-a-long-random-secret", "dev-only-insecure"}


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()      # allow trailing " # comment"
        os.environ.setdefault(key.strip(), value)


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_db_path() -> str:
    p = Path(os.environ.get("DB_PATH", "creative_brief.db"))
    return str(p if p.is_absolute() else (BASE_DIR / p).resolve())


def _secret() -> str:
    value = os.environ.get("SECRET_KEY", "").strip()
    if value in PLACEHOLDER_SECRETS:
        log.warning("SECRET_KEY is not set: using a random per-process key. "
                    "Logins will be invalidated whenever the server restarts.")
        return secrets.token_hex(32)
    return value


@dataclass(frozen=True)
class Settings:
    secret_key: str
    db_path: str
    max_upload_bytes: int
    cors_origins: list[str]
    external_ai_enabled: bool
    gemini_api_key: str
    gemini_model: str
    gemini_vision_model: str
    groq_api_key: str
    groq_model: str
    groq_base_url: str
    semantic_search: bool
    embedding_model: str
    token_ttl_seconds: int = field(default=8 * 3600)

    # Hosted AI is usable only when the operator enabled it AND a key exists.
    @property
    def groq_ready(self) -> bool:
        return self.external_ai_enabled and bool(self.groq_api_key)

    @property
    def gemini_ready(self) -> bool:
        return self.external_ai_enabled and bool(self.gemini_api_key)

    @property
    def hosted_ai_ready(self) -> bool:
        return self.groq_ready or self.gemini_ready


def load_settings() -> Settings:
    _load_env_file(BASE_DIR / ".env")
    env = os.environ.get
    origins = env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,"
                                  "http://localhost:4173,http://127.0.0.1:4173")
    gemini_model = env("GEMINI_MODEL", "gemini-2.0-flash")
    return Settings(
        secret_key=_secret(),
        db_path=_resolve_db_path(),
        max_upload_bytes=int(env("MAX_UPLOAD_MB", "10")) * 1024 * 1024,
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        external_ai_enabled=_flag("EXTERNAL_AI_ENABLED"),
        gemini_api_key=env("GEMINI_API_KEY", ""),
        gemini_model=gemini_model,
        gemini_vision_model=env("GEMINI_VISION_MODEL", gemini_model),
        groq_api_key=env("GROQ_API_KEY", ""),
        groq_model=env("GROQ_MODEL", "openai/gpt-oss-120b"),
        groq_base_url=env("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/"),
        semantic_search=_flag("SEMANTIC_SEARCH"),
        embedding_model=env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
    )


settings = load_settings()
