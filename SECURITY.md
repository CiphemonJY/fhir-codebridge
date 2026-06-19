# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in fhir-codebridge, please report it responsibly:

1. **Do NOT open a public GitHub issue.**
2. **Email the maintainer directly** via GitHub's security advisory feature:
   - Go to https://github.com/CiphemonJY/fhir-codebridge/security/advisories/new
   - Or use "Report a vulnerability" under the Security tab
3. **Include:** description of the issue, steps to reproduce, potential impact, and any suggested fixes.
4. **Response time:** within 72 hours.

## Security Features

fhir-codebridge is designed for healthcare environments where data privacy is critical:

- **On-premises deployment:** No PHI leaves your network. No cloud dependencies.
- **API key authentication:** Role-based access (admin / read-only). Constant-time key comparison.
- **Audit logging:** Every request logged (JSON Lines format). HIPAA §164.312(b) compliant.
- **Rate limiting:** In-memory token bucket (100 req/60s default, configurable).
- **Docker secrets:** API keys stored as files, not plaintext environment variables.
- **Non-root container:** Docker image runs as unprivileged user.
- **UMLS guardrail:** Rate-limited (5 req/s) + cached (1h TTL). Patient context stripped before external API calls.

## Security Configuration

| Setting | Default | Recommendation |
|---------|---------|----------------|
| Auth | Enabled (required) | Keep enabled in production |
| CORS | Same-origin only | Set `CODEBRIDGE_CORS_ORIGINS` for cross-origin |
| Rate limit | 100 req/60s | Lower for public-facing deployments |
| Docker | Non-root user | Keep — do not override |
| Audit log | `data/audit.log` | Mount to persistent volume in production |

## Scope

**In scope:** fhir-codebridge server code, client SDK, Docker configuration, CI/CD workflows.

**Out of scope:** UMLS/NLM API security (governed by NLM terms), your institution's network security, Docker host hardening.

## Disclosure Policy

- Vulnerabilities are disclosed after a fix is available and deployed.
- We coordinate with reporters on disclosure timing.
- Credit is given to reporters (unless they prefer to remain anonymous).
