# Creative Brief technical pipeline

## A. Ingestion
FastAPI receives the creative. PyMuPDF extracts/renders PDF content, python-docx extracts DOCX text, Tesseract extracts image text. Gemini vision may describe image elements when consent, workspace permission, feature flag and API key are all present.

## B. Guideline knowledge
Guideline uploads are extracted and chunked into organization-scoped records. The MVP retrieves relevant chunks through lexical matching. Embeddings/vector retrieval can be added without changing the rule record schema. Government rules and company rules should be tagged separately and retain source/version metadata.

## C. Evaluation
Python checks explicit forbidden phrases and compares likely claims against approved-claim records. Groq is the primary configured text-review provider; Gemini is a fallback. The model is instructed to use only retrieved evidence and return RED/ORANGE/GREEN, where ORANGE represents uncertainty. These flags are screening states, not a legal determination.

## D. Visual brand checks — next implementation module
OpenCV should measure colour regions, contrast and geometry against machine-readable brand rules. Object detection/logo matching should return bounding boxes and confidence. Gemini can classify context, but should not be the only source for exact colour measurement. No object or colour should be considered a violation unless the applicable guideline and its scope support that conclusion.

## E. Fact, tone and language checks — next implementation modules
- Fact verification: extract atomic claims, retrieve trusted sources, compare claim/evidence, store citations and classify supported/contradicted/unverified/review.
- Tone: compare text against an explicit company voice profile; use sentiment/emotion classifiers as signals, not as final verdicts.
- Language: Lingua or fastText segment detection plus company policy (English-only, Hindi-only, bilingual etc.). Romanized Hindi and code-switching need context-aware handling.

## F. Reporting and workflow
Findings retain the text/element, category, status, evidence, suggested correction and source context. Reviewers can accept/reject/dismiss/request evidence/comment. Assignments and approvals create audit events. The suggestion feature gives concise recommendations only; it does not rewrite entire documents or regenerate images.

## G. Privacy
Tenant-scoped database queries, role checks, per-assessment consent, workspace-level external-AI policy, and persisted privacy settings are implemented in the starter. Production deployment still needs HTTPS, managed secrets, encrypted backups/storage, a deletion/retention worker, and download-policy enforcement.
