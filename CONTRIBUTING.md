# Contributing to fhir-codebridge

Thank you for your interest in contributing! fhir-codebridge is an open source FHIR terminology mapping service. We welcome contributions from healthcare IT professionals, developers, clinical coders, and researchers.

## Ways to Contribute

### High Priority

1. **Terminology data** — help expand pre-loaded SNOMED CT and LOINC coverage
2. **Mapping bundles** — verified ICD-10 → SNOMED, LOINC normalization, RxNorm crosswalks
3. **EHR integration examples** — Epic, Cerner, Meditech reference patterns
4. **Testing** — run the benchmark suite against your real-world data and report results
5. **Documentation** — INSTALL.md improvements, deployment guides for specific environments

### Welcome Contributions

- Bug fixes and error handling improvements
- Performance optimizations (caching, indexing)
- New coding system support (CPT, CVX, ICD-10-PCS)
- International terminology support (ICD-10-AM, SNOMED CT country editions)
- Docker/deployment improvements
- Security hardening

## Development Setup

### Prerequisites

- Python 3.10+
- Docker and Docker Compose (for testing deployments)
- Optional: UMLS API key (for full terminology testing)

### Setup

```bash
# Clone
git clone https://github.com/CiphemonJY/fhir-codebridge.git
cd fhir-codebridge

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn scripts.api.server:app --reload --port 8000

# Run tests
python3 scripts/calibration_test_100.py
```

## Code Style

- Follow PEP 8
- Use Black for formatting: `black .`
- Add docstrings to public functions
- Keep functions focused and testable
- Comments for complex clinical logic

## Pull Request Process

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/your-feature`)
3. **Test** your changes — run the benchmark suite and verify it passes
4. **Commit** with a clear message (`git commit -m 'Add LOINC common labs expansion'`)
5. **Push** to your fork (`git push origin feature/your-feature`)
6. **Open** a Pull Request with:
   - What changed and why
   - Test results
   - Any breaking changes

### PR Checklist

- [ ] Code follows style guidelines (PEP 8, Black)
- [ ] Tests pass locally
- [ ] Documentation updated (README, INSTALL, or inline)
- [ ] No hardcoded secrets or API keys
- [ ] Audit logging covers any new endpoints

## Terminology Data Contributions

If you're contributing terminology data or mapping bundles:

1. **Format:** JSON array of `{"code": "...", "system": "...", "display": "..."}`
2. **Source:** Must be from a redistributable source (public domain, UMLS with key, or your own verified mappings)
3. **Verification:** Include the source and verification method in your PR
4. **Licensing:** Do not include SNOMED CT full edition (requires license). Use the problem-list subset or UMLS API.

## Reporting Issues

- **Bug reports:** Use GitHub Issues. Include: OS, Python version, Docker version, error message, steps to reproduce.
- **Feature requests:** Use GitHub Issues with the `enhancement` label. Describe the use case, not just the feature.
- **Security vulnerabilities:** Do NOT open a public issue. Email the maintainer directly.

## Communication

- **Issues:** Bug reports, feature requests, questions
- **Pull Requests:** Code and data contributions
- **Discussions:** General questions and ideas (if enabled)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Project Structure

```
fhir-codebridge/
├── scripts/
│   ├── api/
│   │   └── server.py          # FastAPI server with 5 endpoints
│   └── rag/
│       └── rag_lookup.py      # RAG lookup engine
├── data/
│   ├── terminology_parsed/    # JSON terminology files (loaded at startup)
│   └── terminology_raw/        # UMLS MRCONSO.RRF (hospital-provided)
├── examples/
│   ├── curl_examples.sh        # curl API examples
│   ├── client_example.py       # Python client
│   ├── postman_collection.json # Postman collection
│   └── nginx/
│       └── nginx.conf          # TLS reverse proxy config
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── README.md
├── INSTALL.md
├── BENCHMARK.md
├── COMMERCIAL.md
├── SNOMED_LICENSE.md
├── CONTRIBUTING.md
├── LICENSE
└── requirements.txt
```

Thank you for helping make terminology mapping accessible to every hospital! 🏥