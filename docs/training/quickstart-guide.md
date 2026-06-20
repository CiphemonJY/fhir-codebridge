# fhir-codebridge Quick Start Guide

*First lookup in minutes. No coding experience required.*

## What This Tool Does

fhir-codebridge translates medical codes between different coding systems.
For example: if you have ICD-10-CM code `E11.9` (Type 2 diabetes) and need to
know the equivalent SNOMED-CT code, this tool finds it for you.

## Step 1: Start the Service

**Option A — Docker (recommended):**
```bash
docker run -p 8000:8000 -e CODEBRIDGE_AUTH_DISABLED=1 ghcr.io/ciphemonjy/fhir-codebridge:latest
```

**Option B — Python:**
```bash
pip install fhir-codebridge
python -m uvicorn scripts.api.server:app --port 8000
```

## Step 2: Open the Web UI

Open your browser and go to: **http://localhost:8000**

You'll see four tabs:
- **Dashboard** — shows service status and loaded terminology
- **Single Lookup** — look up one code at a time
- **Bulk Upload** — process a CSV file of codes
- **Analytics** — view denial pattern analytics and lookup statistics

## Step 3: Your First Lookup

1. Click the **Single Lookup** tab
2. Type a code: `E11.9`
3. Select system: `ICD-10-CM`
4. Click **Map It**

You'll see:
- The code description: "Type 2 diabetes mellitus without complications"
- Source authority: "CMS 2027 ICD-10-CM (public domain)"
- Confidence: **Verified** (green badge)

## Step 4: Bulk Upload (Excel users)

1. Create a CSV file with a column called `code` containing your diagnosis codes
2. Click the **Bulk Upload** tab
3. Drag your CSV file into the upload zone
4. Select the source system (e.g., ICD-10-CM)
5. Click **Map Codes**
6. A results CSV downloads automatically — open it in Excel

Results columns:
- `original_code` — the code you uploaded
- `original_description` — what that code means
- `mapped_code` — the equivalent code in the target system
- `mapped_description` — what the mapped code means
- `confidence` — how confident the mapping is (0.0 to 1.0)
- `confidence_label` — High, Medium, Low, or Very Low
- `action` — auto_accept, review, or reject

## Understanding Confidence Levels

| Label | Score | Meaning |
|-------|-------|---------|
| High | ≥0.95 | Exact match or crosswalk — appropriate for automated use |
| Medium | ≥0.80 | Strong fuzzy match — review recommended |
| Low | ≥0.60 | Weak match — human review required |
| Very Low | <0.60 | No reliable match found |

## Provenance — Why Should You Trust This?

Every lookup result includes a `provenance` block showing:
- **source_authority** — where the data came from (CMS, NLM, etc.)
- **verified_date** — when the mapping was last verified
- **mapping_method** — how the match was found (exact, crosswalk, fuzzy)
- **confidence_level** — trust level of the result

This is auditable — compliance officers can verify the data source.

## Glossary

| Term | Meaning |
|------|---------|
| ICD-10-CM | International Classification of Diseases, 10th rev., Clinical Modification. Used for diagnoses. Updates Oct 1 annually. |
| SNOMED-CT | Systematized Nomenclature of Medicine — Clinical Terms. Used for clinical documentation. |
| LOINC | Logical Observation Identifiers Names and Codes. Used for lab tests and observations. |
| RxNorm | Normalized naming system for clinical drugs. Updates monthly. |
| CDT | Current Dental Terminology. Used for dental procedures. |
| FHIR | Fast Healthcare Interoperability Resources. A standard for exchanging healthcare data. |
| Crosswalk | A mapping between two coding systems (e.g., ICD-10-CM ↔ SNOMED-CT). |
| RAG | Retrieval-Augmented Generation. The lookup engine that finds codes. |
| UMLS | Unified Medical Language System. NLM's comprehensive terminology resource. |

## Troubleshooting

**"No results found"** — The code may not be in the loaded terminology set. Without UMLS data loaded, only shipped data (123K terms) is available.

**"Rate limit exceeded"** — You're making too many requests too fast. Default is 100 requests/minute. Adjust with `CODEBRIDGE_RATE_LIMIT_REQUESTS` env var.

**"Authentication required"** — Set `CODEBRIDGE_API_KEYS` env var or use `CODEBRIDGE_AUTH_DISABLED=1` for testing.

**Need more help?** See [INSTALL.md](../INSTALL.md) or [open an issue](https://github.com/CiphemonJY/fhir-codebridge/issues).
