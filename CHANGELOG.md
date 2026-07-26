# Changelog

All notable changes to fhir-codebridge are documented here.
Versions follow [semantic versioning](https://semver.org/).

## [0.5.0] — 2026-07-25

A minor rather than a patch bump: the routing fixes below change what the
service returns for an absent code, and `threshold` now does something it
previously did not. Anyone depending on the old behaviour will see a difference,
even though the old behaviour was wrong.

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
- `tests/test_routing_safety.py` — 53 tests covering the two routing fixes
  against the shipped terminology data, the perturbation builder, and the
  threshold's round trip through the HTTP layer. That last one matters: the
  threshold defect was declared in the request model and dropped at the
  endpoint, which no engine-level test can catch.
- `scripts/screenshots.py` — regenerates `docs/screenshots/` against a running
  instance, so the images do not drift from the shipped version by hand. Needs
  playwright, a development dependency the service does not import.

### Changed
- `BENCHMARK.md` calibration section reports both labelled sets and states what
  each one cannot measure.
- `README.md` confidence section described a defect that the same release fixes.
  It told readers every mapping emitted at 0.60 and at 0.80 was wrong; the engine
  no longer emits those at all. It also claimed 100% accuracy on known terms,
  which covers exact retrieval only and reads as a claim about real queries. Both
  now state what the two labelled sets measured, including that accuracy inside
  the review band is 0.672 [0.547, 0.777] and AUC on varied display text is 0.981
  rather than perfect. Checkmark badges dropped from the roadmap and coverage
  table.
- The web UI's API-key input was preceded by a stray `</div>` that closed
  `div.container` early, so the browser closed `<nav>` to match and the field
  rendered outside the centred container on every page. It now sits inside the
  nav where its `margin-left:auto` was written to work.
- `docs/screenshots/` recaptured against this version; the previous images were
  taken against v0.2.0 and v0.3.1 and still showed those versions.

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
