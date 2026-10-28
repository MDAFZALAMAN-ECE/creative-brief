# Creative Brief — Complete starter project

A fresh project bundle for the Creative Brief brand-governance workflow. The frontend is a responsive React/Vite workspace; the backend is FastAPI with SQLite, tenant-scoped records, guideline ingestion, review assignments, audit events, external-AI consent gates, and persisted workspace privacy preferences.

## Product workflow

1. Upload a creative (image, PDF, DOCX, TXT or text).
2. Extract text and elements using Tesseract/PyMuPDF/python-docx and optionally Gemini vision (only when the user consents, the workspace allows external AI, the feature flag is enabled and a key is configured).
3. Retrieve applicable government/regulatory parameters and company guidelines from the workspace's guideline collection.
4. Run evidence-grounded assessment with the configured Groq/Gemini text provider and deterministic phrase/approved-claim checks.
5. Show findings and focused suggestions; the UI does not include a chatbot or automatic full-document/image regeneration.
6. Assign reviewers, record finding decisions, and approve/reject/request changes through the workflow endpoints.
7. Manage company-specific guideline uploads, team roles, audit records and workspace privacy preferences.

## Important implementation status

This is a complete runnable starter bundle, **not a claim that every planned checker is finished**. The current backend implements OCR/document extraction, optional Gemini vision extraction, keyword-based retrieval, evidence-grounded model review, approved-claim/forbidden-phrase checks, findings, assignments, approvals, guideline ingestion and privacy preferences. The dedicated external-source fact verifier, robust language/tone classifiers, OpenCV colour-rule engine, specialist object/logo detection, automated retention worker, and production download-policy enforcement remain implementation tasks. The UI labels preview data where records are not backed by the API.

Regulatory and brand checks return screening findings, not definitive legal advice. Missing evidence is not proof of a false claim, and no finding is not proof of full compliance.

## Backend layout

```
backend/app/
  main.py          app entry point (CORS, routers, static frontend)
  config.py        settings from backend/.env
  database.py      SQLite schema, migrations, per-request connections, audit helper
  security.py      password hashing, signed tokens, role dependencies
  extraction.py    PDF / DOCX / image / text extraction, chunking, element splitting
  retrieval.py     keyword retrieval + optional semantic search (sentence-transformers)
  evaluation.py    rule checks + evidence-grounded review pipeline (one lens per guideline collection)
  ai.py            optional Groq / Gemini calls (never used without consent + workspace policy + key)
  categories.py    category registry and category -> guideline-collection mappings
  routers/         auth, knowledge (guidelines/categories), contents, workflow, governance
backend/tests/     pytest suite (python -m pytest from backend/)
```

## Requirements

- Node.js 18+ (Node 20+ recommended)
- Python 3.11+
- Tesseract OCR installed separately if OCR is required

## Run on Windows

1. Extract the ZIP.
2. Copy `backend/.env.example` to `backend/.env` and set a unique `SECRET_KEY`. Add provider keys only if needed. Set `EXTERNAL_AI_ENABLED=true` only when you're ready to permit hosted calls.
3. Open a terminal at the project root and run:

```bat
start-backend-windows.bat
```

4. In another terminal, run:

```bat
start-frontend-windows.bat
```

5. Open the Vite URL, normally `http://localhost:5173`.

## Run manually

Backend:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend (another terminal):

```bash
cd frontend
npm install
npm run dev
```

## Optional: semantic search (sentence-transformers)

Keyword retrieval works out of the box. For embedding-based retrieval:

```bash
cd backend
python -m pip install -r requirements-semantic.txt
# then set SEMANTIC_SEARCH=true in backend/.env and restart
```

**VS Code says `Import "sentence_transformers" could not be resolved`?** The package is not installed in the
interpreter VS Code is using. Press `Ctrl+Shift+P` -> *Python: Select Interpreter* -> choose `backend/.venv`,
run the install above using that environment, then run *Developer: Reload Window*. The package installs as
`sentence-transformers` (hyphen) but imports as `sentence_transformers` (underscore). `GET /api/v1/health`
shows `sentence_transformers_installed` and `semantic_embeddings`. If the package or model is unavailable the
app logs a warning and falls back to keyword retrieval instead of failing.

## API and configuration

- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/api/v1/health`
- Frontend API base: `frontend/.env.local` with `VITE_API_BASE=http://127.0.0.1:8000`
- Backend configuration: `backend/.env`

Never commit API keys, database files or `.env` files. Use HTTPS, strong secrets, managed encrypted storage and a production database before deployment. Review provider retention/data-use terms before uploading confidential creatives.
