# Changelog

All notable changes to fhir-codebridge are documented here.
Versions follow [semantic versioning](https://semver.org/).

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
- 123,080 verified terms (ICD-10-CM, RxNorm, CDT, LOINC, crosswalk)
- RBAC with API key authentication
- Audit logging (JSONL format)
- Docker deployment with secrets support
- Quickstart installers (`quickstart.sh`, `docker-quickstart.sh`)
- Documentation: README, INSTALL, BENCHMARK, COMMERCIAL, CONTRIBUTING, SNOMED_LICENSE
- Examples: curl scripts, Python client, Postman collection, nginx TLS config

### Security
- MIT license
- No hallucinated terminology data — all entries from official sources
