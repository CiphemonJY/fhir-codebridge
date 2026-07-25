# Changelog

All notable changes to fhir-codebridge are documented here.
Versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Fixed
- A code absent from every loaded system could be answered with a different, real
  code. Terminology rows whose `display` is their own code string (20 in
  `cdt.json`, e.g. `{"code": "D0360", "display": "D0360"}`) were indexed as
  display text, so an unknown code retried as display text string-matched them at
  0.6–0.8 confidence and the router forwarded the result to `review`. Such rows
  are no longer added to the display index; they remain in the code index, so
  exact lookup of those codes is unchanged. Every `by_display` write now goes
  through one funnel, `RAGLookup._index_display`.
- `map_with_confidence` no longer retries a failed code lookup as display text
  unless the string reads as a clinical term. See
  `RAGLookup.looks_like_display_text`: whitespace or no digits means prose, and
  the curated synonym and abbreviation tables cover digit-bearing terms such as
  `t2dm`. This is a second, independent guard on the same failure.
- `threshold` is applied. `LookupRequest.threshold` and
  `CodeBridge.lookup(threshold=)` were accepted and never forwarded;
  `map_with_confidence` hardcoded 0.5. It now takes and forwards the argument.
  The default is 0.5 at every layer, so callers that never set it see unchanged
  results — the field previously advertised 0.6 while 0.5 was in force, and 0.5
  is the behaviour that was measured. It affects the fuzzy display path only; an
  exact code hit scores 1.0 and is returned regardless.

### Added
- `scripts/calibration_report.py --build-perturbation-set` — a labelled set built
  by rewriting the display text of terms that are in the terminology (case,
  punctuation, whitespace, a typo, a transposed word) and querying by display.
  The correct answer is known by construction, so labels stay derived rather than
  judged. This is the first set that puts genuine correct and incorrect mappings
  inside the 0.60–0.95 band the review threshold governs. Perturbations that
  remove clinical content (`word_drop`, `truncate`) can name a different real
  concept, so those rows carry `correct: null` and await adjudication.
- Per-perturbation accuracy table in the report, so a pooled figure cannot hide a
  weak stratum.
- `tests/test_routing_safety.py` — 50 tests covering the two routing fixes
  against the shipped terminology data, and the perturbation builder.

### Changed
- `BENCHMARK.md` calibration section reports both labelled sets and states what
  each one cannot measure.

## [0.4.1] — 2026-06-19

### Added
- Payer-specific rule engine with YAML configuration (`config/payer_rules/`)
- `GET /payer/rules` — list configured payer rule sets
- `GET /payer/rules/{name}` — get specific payer rule details
- `POST /validate/payer` — validate codes against payer-specific rules
- Denial pattern analytics (4th web UI tab: Analytics)
- Sample payer rules: Medicare, Texas Medicaid

### Fixed
- Web UI JS quote escaping in Analytics tab (broke all JavaScript on page)
- `showTab()` function missing 'analytics' tab
- Missing analytics tab div in HTML

## [0.4.0] — 2026-06-19

### Added
- `POST /validate` — pre-submission code validation (pass/warning/fail)
- `GET /analytics/denials` — denial pattern analytics from audit log
- `POST /bulk/stream` — streaming bulk CSV for 200K+ row files
- Scheduled terminology updates via GitHub Actions cron (monthly auto-PR)
- `scripts/download_cms_icd10.py` and `scripts/download_rxnorm.py`

## [0.3.2] — 2026-06-19

### Added
- Structured JSON logging (`scripts/api/logging_config.py`) — SIEM-ingestible
- API rate limiting (token bucket, 100 req/60s default, configurable)
- Training materials: `docs/training/quickstart-guide.md`, `glossary.md`, `admin-guide.md`

## [0.3.1] — 2026-06-19

### Added
- Mapping provenance metadata on every `/lookup` response
- `GET /terminology/version` endpoint for audit compliance
- Deep health check: per-system data status, missing critical systems, data integrity
- `terminology_versions` dict tracks all loaded terminology file versions

## [0.3.0] — 2026-06-19

### Changed
- **Breaking:** `LISA_` environment variables renamed to `CODEBRIDGE_` prefix
- All 7 env vars renamed across 12 files

### Added
- Pip-installable client SDK (`codebridge` package) with CLI entry point
- CI/CD via GitHub Actions (matrix Python 3.11+3.12, pytest + Docker build)
- `GET /metrics` endpoint (Prometheus-compatible)
- Web UI: single HTML file served at `GET /` with 4 tabs
- `POST /bulk` endpoint for CSV file upload and processing
- `python-multipart` added to core dependencies

### Fixed
- Auth bypass: auth now enabled by default
- CORS: configurable via env var, same-origin only if not set
- UMLS API key leak prevention
- Audit log silent failure handling

## [0.2.0] — 2026-06-19

### Added
- Initial public release
- RAG lookup engine (100% accuracy on known terms)
- 5 API endpoints: `/health`, `/stats`, `/systems`, `/lookup`, `/$translate`
- 123,079 sourced terms (ICD-10-CM, RxNorm, CDT, LOINC, crosswalk)
- RBAC with API key authentication
- Audit logging (JSONL format)
- Docker deployment with secrets support
- Quickstart installers (`quickstart.sh`, `docker-quickstart.sh`)
- Documentation: README, INSTALL, BENCHMARK, COMMERCIAL, CONTRIBUTING, SNOMED_LICENSE
- Examples: curl scripts, Python client, Postman collection, nginx TLS config

### Security
- MIT license
- No hallucinated terminology data — all entries from official sources
