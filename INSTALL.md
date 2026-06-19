# Installation Guide

## Prerequisites

- **Docker 24+** and **Docker Compose v2** (or Python 3.10+ without Docker)
- **4GB RAM** minimum (8GB recommended for UMLS full load)
- **UMLS API key** (optional but recommended — free, 1-2 business day approval)
- **Network:** outbound HTTPS to `uts.nlm.nih.gov` (for UMLS API, if using key)
- **Ports:** 8000 (default, configurable)

## Option 1: Docker (Recommended)

### Step 1: Clone the repository

```bash
git clone https://github.com/CiphemonJY/fhir-codebridge.git
cd fhir-codebridge
```

### Step 2: Configure secrets

```bash
# Copy the example config
cp .env.example .env

# Generate strong API keys (don't use the defaults in production)
ADMIN_KEY=$(openssl rand -hex 32)
READ_KEY=$(openssl rand -hex 32)

# Edit .env and set:
# CODEBRIDGE_API_KEYS=${ADMIN_KEY}:admin,${READ_KEY}:read
# UMLS_API_KEY=your-umls-key (if you have one)

# For Docker secrets (more secure, recommended for production):
mkdir -p secrets
echo "your-umls-api-key" > secrets/umls_api_key.txt
echo "${ADMIN_KEY}:admin,${READ_KEY}:read" > secrets/lisa_api_keys.txt
chmod 600 secrets/*.txt
```

### Step 3: Start the service

```bash
docker compose up -d
```

### Step 4: Verify it's running

```bash
curl http://localhost:8000/health
```

You should see:
```json
{
    "status": "ok",
    "service": "fhir-codebridge FHIR Terminology Service",
    "version": "0.2.0",
    "terms_loaded": 123080,
    "umls_enabled": false,
    "auth_enabled": true
}
```

Note: `terms_loaded` shows ~123K with shipped data (CMS ICD-10-CM + NLM RxNorm API + CDT + LOINC core). After loading UMLS, this jumps to 600K+.

### Step 5: Test a lookup

```bash
# With auth enabled, include your API key:
curl -X POST http://localhost:8000/lookup \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR-ADMIN-KEY" \
  -d '{"code": "D0120", "system": "CDT"}'
```

This returns a CDT code lookup (periodic oral evaluation). For ICD-10-CM or SNOMED-CT lookups, you'll need to load UMLS data first (see below).

## Option 2: Without Docker

```bash
git clone https://github.com/CiphemonJY/fhir-codebridge.git
cd fhir-codebridge
pip install -r requirements.txt

# Set environment variables
export CODEBRIDGE_API_KEYS="admin-key:admin,readonly-key:read"
export CODEBRIDGE_UMLS_API_KEY=your-umls-key  # optional

uvicorn scripts.api.server:app --host 0.0.0.0 --port 8000
```

## Getting a Free UMLS API Key

UMLS (Unified Medical Language System) is published by the National Library of Medicine. It connects all major clinical coding systems to each other. The API key is **free** but requires registration.

1. Go to https://uts.nlm.nih.gov/uts/signup
2. Register with your **organizational email** (not Gmail/Yahoo)
3. Wait for approval (usually 1-2 business days, can take up to 5)
4. Log in and find your API key in your profile page
5. Put it in your `.env` file or Docker secret

**What it unlocks:**
- SNOMED CT (~350,000 clinical concepts)
- LOINC (~90,000 lab tests)
- Cross-system mappings maintained by NLM

**What works without it:**
- ICD-10-CM (74,879 terms) — full CMS 2027 code set, all diagnoses ✅
- RxNorm (47,780 terms) — ingredients, brand names, clinical drugs from NLM API ✅
- CDT (397 terms) — full dental procedure codes ✅
- LOINC (23 terms) — core vital signs only (full set needs UMLS/registration)
- Crosswalk (1,898 verified mappings) — cross-system code mapping
- Total: 123,080 verified terms + 1,898 crosswalk mappings

**Tip:** The service ships with 123K+ terms covering ICD-10-CM, RxNorm, and CDT. Load UMLS to add SNOMED-CT (~350K) and full LOINC (~90K).

## Firewall/Network Configuration

Hospitals often have restricted networks. Here's what fhir-codebridge needs:

### Required outbound domains (only if using UMLS key)

| Domain | Port | Purpose |
|--------|------|---------|
| `uts.nlm.nih.gov` | 443 | UMLS REST API for terminology lookups |
| `rxnav.nlm.nih.gov` | 443 | RxNorm REST API (if using RxNorm web service) |

### Internal-only mode (no outbound access)

If your network has no outbound internet access, fhir-codebridge works in limited mode with the pre-loaded terms. You can also:

1. Download UMLS Metathesaurus files on a separate machine
2. Drop `MRCONSO.RRF` into `data/terminology_raw/umls/`
3. The service auto-detects and loads it on startup

### Reverse proxy (TLS termination)

Hospitals should not run the API over plain HTTP in production. Use nginx or Caddy for TLS:

- **nginx example:** See `examples/nginx/nginx.conf` for a complete configuration with TLS, rate limiting, and security headers
- **Caddy (simpler):** `reverse_proxy localhost:8000` with automatic HTTPS

### Docker port binding

By default, the service binds to `0.0.0.0:8000`. For production, bind to localhost only and use a reverse proxy:

```yaml
# docker-compose.yml (production override)
services:
  fhir-codebridge:
    ports:
      - "127.0.0.1:8000:8000"  # localhost only
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CODEBRIDGE_UMLS_API_KEY` | (none) | UMLS UTS API key for full terminology access |
| `CODEBRIDGE_UMLS_API_KEY_FILE` | (none) | Path to Docker secret file containing UMLS key |
| `CODEBRIDGE_API_KEYS` | (none) | Comma-separated API keys with roles (`key:role`) |
| `CODEBRIDGE_API_KEYS_FILE` | (none) | Path to Docker secret file containing API keys |
| `CODEBRIDGE_PORT` | 8000 | Port for the API server |
| `CODEBRIDGE_AUDIT_LOG` | `data/audit.log` | Path to audit log file |

## Security Features

### API Key Authentication

Set `CODEBRIDGE_API_KEYS` (env var or Docker secret) to enable auth.
Format: `key1:role1,key2:role2`

| Role | Permissions |
|------|-------------|
| `admin` | All endpoints + audit log access |
| `read` | `/lookup`, `/$translate`, `/systems`, `/stats` |

If no keys are configured, auth is disabled (open mode — for local dev only).

### Audit Logging

Every API request is logged to `data/audit.log` (JSON Lines format):

```json
{"ts":"2026-06-19T04:20:00Z","action":"lookup","ip":"10.0.0.1","endpoint":"/lookup","detail":{"code":"E11.9","system":"ICD-10-CM","found":true,"action":"auto_accept","confidence":1.0}}
```

Query the audit log (admin only):

```bash
curl -H "X-API-Key: YOUR-ADMIN-KEY" http://localhost:8000/audit?limit=50
```

### Docker Secrets

Production deployments should use Docker secrets (or Kubernetes secrets) rather than plaintext environment variables. The service reads from:
- `CODEBRIDGE_UMLS_API_KEY_FILE` — path to UMLS API key file
- `CODEBRIDGE_API_KEYS_FILE` — path to API keys file

See `docker-compose.yml` for the complete setup.

### UMLS API Guardrail

UMLS UTS API calls are rate-limited (max 5 requests/second) and cached (1 hour TTL) to prevent API abuse and reduce latency for repeated lookups. Patient context is stripped before external API calls to prevent PHI leakage.

## Backup and Recovery

### What to back up

| Data | Location | Persists? |
|------|----------|-----------|
| Audit logs | `data/audit.log` (Docker volume) | ✅ |
| UMLS cache | In-memory | ❌ (rebuilt on startup) |
| API keys | Docker secrets / env vars | ✅ (in your config) |
| Terminology data | `data/terminology_parsed/` | ✅ (in the image) |

### Backup commands

```bash
# Back up audit logs and data
docker compose exec fhir-codebridge tar czf /tmp/backup.tar.gz data/
docker compose cp fhir-codebridge:/tmp/backup.tar.gz ./backup-$(date +%Y%m%d).tar.gz

# Restore
docker compose cp ./backup-20260619.tar.gz fhir-codebridge:/tmp/
docker compose exec fhir-codebridge tar xzf /tmp/backup-20260619.tar.gz -C /
docker compose restart
```

## Troubleshooting

**Service won't start:**
- Check port 8000 isn't already in use: `lsof -i :8000`
- Check Docker logs: `docker compose logs`
- Check secrets files exist if using Docker secrets
- Ensure Docker has at least 4GB memory allocated

**Authentication errors (401):**
- Verify `X-API-Key` header is set on requests
- Check that keys are properly configured in env var or secret file
- Default keys in `.env.example` are placeholders — generate your own

**Audit log empty:**
- Verify `data/` directory is writable by the container
- Check `CODEBRIDGE_AUDIT_LOG` path if using custom location

**UMLS lookups not working:**
- Verify UMLS data is loaded: `curl http://localhost:8000/health` — `umls_enabled` should be `true`
- Check that `MRCONSO.RRF` is in `data/terminology_raw/umls/`
- Ensure outbound HTTPS to `uts.nlm.nih.gov` is allowed by your firewall
- UMLS calls are rate-limited (5/s) and cached (1h) — check audit log for errors

**Out of memory:**
- Increase Docker memory allocation to 4GB+
- Full UMLS load (MRCONSO.RRF) requires 8GB+ RAM
- Without UMLS, the service uses <512MB RAM

**Want more terminology data?**
- Place UMLS Metathesaurus `MRCONSO.RRF` in `data/terminology_raw/umls/` — adds 600K+ terms
- Or download individual systems (ICD-10-CM from CMS, RxNorm from NLM) — see `data/terminology_parsed/README.md`
- Run `python3 scripts/build_terminology_data.py --umls /path/to/MRCONSO.RRF` to convert
- The service auto-detects new data files on restart

## Production Hardening Checklist

Before deploying in production:

- [ ] **Change default API keys** — generate with `openssl rand -hex 32`
- [ ] **Enable TLS** — use nginx or Caddy reverse proxy (see `examples/nginx/`)
- [ ] **Set up log rotation** — audit logs grow over time
- [ ] **Configure audit log retention** — default 6 years for HIPAA compliance
- [ ] **Restrict port binding** — bind to `127.0.0.1` + reverse proxy
- [ ] **Set up automated backups** — at minimum, daily audit log backup
- [ ] **Monitor health endpoint** — `GET /health` for uptime monitoring
- [ ] **Review UMLS key permissions** — ensure only authorized staff have admin keys
- [ ] **Firewall rules** — restrict outbound to only required NLM domains
- [ ] **Docker resource limits** — set memory and CPU limits in compose file

## API Documentation

Once running, interactive API docs are available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## FHIR Integration

The service implements the FHIR ConceptMap `$translate` operation:

```bash
curl -X POST 'http://localhost:8000/$translate' \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR-KEY" \
  -d '{
    "code": "E11.9",
    "system": "http://hl7.org/fhir/sid/icd-10-cm",
    "target_system": "http://snomed.info/sct"
  }'
```

Supported FHIR system URIs:
- `http://hl7.org/fhir/sid/icd-10-cm` — ICD-10-CM
- `http://snomed.info/sct` — SNOMED-CT
- `http://loinc.org` — LOINC
- `http://www.nlm.nih.gov/research/umls/rxnorm` — RxNorm
- `http://www.ada.org/cdt` — CDT