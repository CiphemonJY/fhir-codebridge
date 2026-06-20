# Deployment Runbook

## Quick Deploy (Docker)

```bash
git clone https://github.com/CiphemonJY/fhir-codebridge.git
cd fhir-codebridge
docker compose up -d
# Service available at http://localhost:8000
```

## Non-Docker Deploy

```bash
git clone https://github.com/CiphemonJY/fhir-codebridge.git
cd fhir-codebridge
pip install -e .
uvicorn scripts.api.server:app --host 0.0.0.0 --port 8000
```

## Configuration

All configuration via environment variables (or Docker secrets):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CODEBRIDGE_API_KEYS` | Recommended | — | Comma-separated `key:role` pairs (`key1:admin,key2:read`) |
| `CODEBRIDGE_AUTH_DISABLED` | No | — | Set to `1` for open mode (NOT for production) |
| `CODEBRIDGE_UMLS_API_KEY` | For UMLS | — | NLM UTS API key (free at https://www.nlm.nih.gov/research/umls/license/license.html) |
| `CODEBRIDGE_CORS_ORIGINS` | No | — | Comma-separated allowed origins |
| `CODEBRIDGE_PORT` | No | 8000 | Server port |
| `CODEBRIDGE_AUDIT_LOG` | No | `data/audit.log` | Audit log file path |
| `CODEBRIDGE_RATE_LIMIT` | No | `1` | Set to `0` to disable rate limiting |
| `CODEBRIDGE_RATE_LIMIT_REQUESTS` | No | 100 | Requests per window per client |
| `CODEBRIDGE_RATE_LIMIT_WINDOW` | No | 60 | Rate limit window in seconds |

## Docker Secrets

For production, use Docker secrets instead of plaintext env vars:

```bash
mkdir -p secrets
echo "your-umls-key" > secrets/umls_api_key.txt
echo "admin-key:admin,read-key:read" > secrets/codebridge_api_keys.txt
docker compose up -d
```

The app reads `*_FILE` env vars that point to secret files.

## Health Check

```bash
curl http://localhost:8000/health
```

Response includes per-system data status and missing critical systems.

## Verification

1. **Check health:** `curl localhost:8000/health` → `"status": "ok"`
2. **Check stats:** `curl -H "X-API-Key: $KEY" localhost:8000/stats` → term counts
3. **Test lookup:** `curl -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"code":"E11.9","system":"ICD-10-CM"}' localhost:8000/lookup`
4. **Check terminology version:** `curl -H "X-API-Key: $KEY" localhost:8000/terminology/version`

## Troubleshooting

| Symptom | Check | Fix |
|---------|-------|-----|
| 401 Unauthorized | `X-API-Key` header present? | Set `CODEBRIDGE_API_KEYS` or `CODEBRIDGE_AUTH_DISABLED=1` (dev only) |
| 429 Too Many Requests | Rate limit hit | Increase `CODEBRIDGE_RATE_LIMIT_REQUESTS` or disable for trusted networks |
| Empty results | Data loaded? | Check `/health` for `terms_loaded` > 0 |
| Slow startup | Large UMLS file? | First load parses MRCONSO.RRF; subsequent restarts use cached JSON |
| Audit log errors | `data/` writable? | `chmod 755 data/` or set `CODEBRIDGE_AUDIT_LOG` to writable path |

## Rollback

```bash
# Stop current container
docker compose down

# Revert to previous image (if using tagged images)
docker compose up -d  # pulls from previous build

# Or revert to previous git commit
git log --oneline -5
git checkout <previous-commit> -- .
docker compose up -d --build
```

## Updating Terminology Data

```bash
# Inside container or local install
python scripts/build_terminology_data.py --umls  # needs UMLS API key
python scripts/build_terminology_data.py          # free data only (ICD-10-CM + RxNorm)
```

Monthly auto-updates are available via the GitHub Actions cron workflow
(`.github/workflows/update-terminology.yml`).
