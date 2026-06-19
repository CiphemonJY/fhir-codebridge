# fhir-codebridge Administrator Guide

*For IT staff deploying fhir-codebridge at a hospital.*

## Deployment

### Docker (recommended)
```bash
docker run -d \
  --name codebridge \
  -p 8000:8000 \
  -e CODEBRIDGE_API_KEYS=your-key:admin \
  -v codebridge-data:/app/data \
  --restart unless-stopped \
  ghcr.io/ciphemonjy/fhir-codebridge:latest
```

### Docker Compose
See `docker-compose.yml` in the repo. Includes health checks and resource limits.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CODEBRIDGE_API_KEYS` | (none) | API keys in `key:role,key:role` format. Without this, auth is enabled with no keys (all requests rejected). |
| `CODEBRIDGE_AUTH_DISABLED` | `0` | Set to `1` for testing only. Never use in production. |
| `CODEBRIDGE_PORT` | `8000` | Server port. |
| `CODEBRIDGE_CORS_ORIGINS` | (none) | Comma-separated allowed origins. Not set = same-origin only. |
| `CODEBRIDGE_AUDIT_LOG` | `data/audit.log` | Audit log file path. JSONL format. |
| `CODEBRIDGE_UMLS_API_KEY` | (none) | NLM UMLS API key for extended lookups. |
| `CODEBRIDGE_RATE_LIMIT` | `1` | Set to `0` to disable rate limiting. |
| `CODEBRIDGE_RATE_LIMIT_REQUESTS` | `100` | Requests per window per client. |
| `CODEBRIDGE_RATE_LIMIT_WINDOW` | `60` | Rate limit window in seconds. |

### Docker Secrets
All env vars support `_FILE` suffix for Docker secrets:
```
CODEBRIDGE_API_KEYS_FILE=/run/secrets/api_keys
```

## Monitoring

### Health Check
```bash
curl http://localhost:8000/health
```
Returns status, terms loaded, systems loaded, missing critical systems, data integrity.

### Prometheus Metrics
```bash
curl http://localhost:8000/metrics
```
Metrics: `codebridge_terms_loaded`, `codebridge_systems_loaded`, `codebridge_up`, `codebridge_umls_enabled`.

### Audit Log
```bash
curl -H "X-API-Key: your-key" http://localhost:8000/audit?limit=100
```
Returns JSONL audit entries with timestamp, action, user, and request details.

## Loading UMLS Data

1. Obtain a UMLS license at https://uts.nlm.nih.gov/uts/signup
2. Download MRCONSO.RRF from the UMLS Metathesaurus
3. Place it in `data/terminology_raw/umls/MRCONSO.RRF`
4. Restart the service — it auto-loads on startup
5. Verify: `curl http://localhost:8000/health` should show 600K+ terms

## Security Checklist

- [ ] `CODEBRIDGE_AUTH_DISABLED` is NOT set (or is `0`)
- [ ] `CODEBRIDGE_API_KEYS` is set with strong keys
- [ ] `CODEBRIDGE_CORS_ORIGINS` is set to specific allowed origins (not wildcard)
- [ ] Audit log is being written and is readable only by admin
- [ ] Docker secrets are used for API keys in production
- [ ] Rate limiting is enabled (default)
- [ ] Service runs behind HTTPS (nginx, Traefik, or cloud load balancer)
