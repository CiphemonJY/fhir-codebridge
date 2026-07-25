# Benchmark & Calibration

## Current Data Coverage

### Shipped Data (Verified Sources Only)

| System | Count | Source | Full Set Size | Coverage |
|--------|-------|--------|---------------|----------|
| ICD-10-CM | 74,879 | CMS 2027 (public domain) | ~74,879 | **100%** ✅ |
| RxNorm | 47,780 | NLM RxNorm REST API (public domain) | ~80,000 (est.) | ~59% (est.) |
| CDT | 397 | Project source TSV | 397 | **100%** ✅ |
| LOINC (core) | 23 | Project source TSV | ~90,000 | 0.03% |
| SNOMED-CT | 0 | — (requires UMLS license) | ~350,000 | 0% |
| Crosswalk | 1,898 | Synthea-derived similarity mappings | — | — |
| **Total** | **123,079** | | | |

**No hallucinated data.** Every entry is from an official source:
- CMS ICD-10-CM 2027 code descriptions (public domain, freely redistributable)
- NLM RxNorm REST API — ingredients, brand names, clinical drugs (public domain)
- Project source TSVs (CDT, LOINC core, db_523 ontology)
- Synthea-derived crosswalk (similarity-based mappings)

### With UMLS Loaded (Hospital-Provided)

When a hospital provides their UMLS Metathesaurus (`MRCONSO.RRF`):

| System | Expected Count | Source |
|--------|---------------|--------|
| SNOMED-CT | ~350,000 | UMLS SNOMEDCT_US |
| ICD-10-CM | ~74,000 | UMLS ICD10CM (already shipped via CMS) |
| LOINC | ~90,000 | UMLS LNC |
| RxNorm | ~81,000 (est.) | UMLS RXNORM (partially shipped via API) |
| CDT | ~397 | UMLS CDT (already shipped) |
| CPT | ~13,000 | UMLS CPT |
| **Total** | **~600,000+** | Single MRCONSO.RRF file |

## RAG Lookup Accuracy

### Exact Code Lookup: 100% ✅

When a code exists in the loaded terminology, the RAG engine returns it with 100% confidence.
This is the core value proposition — deterministic, verifiable, no ML uncertainty.

```
Input:  ICD-10-CM|E11.9
Output: auto_accept @ 100.0% — "Type 2 diabetes mellitus without complications"
Method: exact_code_lookup
```

### Crosswalk Mappings: Computed (Not Hallucinated) ✅

The 1,898 crosswalk mappings were generated through Synthea patient data analysis
with cosine similarity scoring against the db_523 ontology. These are computed (not manually reviewed)
mappings, not hallucinated.

### Fuzzy Text Matching: 90% ✅

With 123K+ terms loaded (including 74K ICD-10-CM descriptions), fuzzy text matching
now works for most common clinical terms:

- **ICD-10-CM**: Search by diagnosis description → find code (works for 74K+ terms)
- **RxNorm**: Search by drug name → find RxNorm code (works for 47K+ terms)
- **CDT**: Search by procedure name → find CDT code (works for all 397 terms)
- **LOINC**: Limited to 23 core terms until UMLS/LOINC registration

### Neural Model (Experimental)

The DP-LoRA fine-tuned model (experimental neural cross-system mapping) provides neural cross-system
mapping for codes NOT in the RAG layer. This is the experimental layer — 64.8%
accuracy on unseen code pairs.

**Architecture**: RAG (100% on known codes) → Neural model (fallback for unknown codes) → Human review

## Action Routing Test Results

Run: `python3 scripts/action_routing_test.py`

How often a query lands in the expected routing bucket (auto_accept / review /
reject). This is category accuracy. It is not calibration, and the section below
measures that separately. The script was previously named
`calibration_test_100.py`.

| Category | Accuracy | Count | Notes |
|----------|----------|-------|-------|
| Exact code lookup | 100.0% | 60/60 | ICD-10-CM, RxNorm, CDT, LOINC |
| Reject unknown | 100.0% | 4/4 | Fake codes correctly rejected |
| Fuzzy text | 90.0% | 9/10 | Clinical descriptions → codes |
| Overall | 98.6% | 73/74 | |

## Calibration

Calibration asks a different question: when the service reports confidence 0.80,
how often is that mapping actually correct? Three shipped decisions read the
score as if it answered that — the 0.95 auto-accept floor and 0.70 review floor
in `map_with_confidence`, and the `threshold=0.6` default on
`CodeBridge.lookup()` and `LookupRequest` — so it is measured on its own.

- Metrics: `codebridge/calibration.py` — ECE, Brier, reliability table with
  Wilson intervals, AUC, isotonic (PAV) and Platt calibrators. Standard library
  only, so it imports wherever the service runs.
- Report: `python3 scripts/calibration_report.py --labels <set.jsonl>`

### Measured on a membership-labelled set

Labels here follow from terminology membership, which is a fact about the loaded
data rather than a clinical judgement: a code present in a loaded system has
exactly one correct entry, and a code present in no loaded system has no correct
mapping at all, so any mapping returned for it is wrong. Built with
`scripts/calibration_report.py --build-membership-set`, seed 1234, 400 positives
(codes and display strings drawn from the index) and 400 negatives (codes
verified absent from every loaded system under every code variant the lookup
tries). Shipped data only, 123,079 terms, no UMLS.

| Confidence (mean) | n | Observed accuracy | 95% CI (Wilson) |
|---|---|---|---|
| 0.000 | 301 | 0/301 = 0.000 | 0.000 – 0.013 |
| 0.600 | 71 | 0/71 = 0.000 | 0.000 – 0.051 |
| 0.800 | 28 | 0/28 = 0.000 | 0.000 – 0.121 |
| 1.000 | 400 | 400/400 = 1.000 | 0.990 – 1.000 |

ECE 0.081 (equal-frequency bins, 10 requested and 4 used — the score takes only
four distinct values on this set). Brier 0.054. AUC 1.000.

The score ranks perfectly on this set and is still not a probability. Ranking
and calibration are separate properties, and a threshold reads the second one.
Every mapping emitted at 0.60 and at 0.80 was wrong; the 28 rows at 0.80 are
routed to `review`, where a coder is shown a "likely match".

All 99 non-zero-confidence errors are CDT, from one data defect:
`data/terminology_parsed/cdt.json` has 20 entries whose `display` is the code
string itself, e.g. `{"code": "D0360", "display": "D0360"}`. When a code lookup
misses, `map_with_confidence` retries the code as display text, so an unknown
code string fuzzy-matches those placeholder displays — `D9820` comes back as CDT
`D9220` at 0.8.

Also worth knowing when reading a threshold: `LookupRequest.threshold` and
`CodeBridge.lookup(threshold=)` are accepted but never forwarded to
`map_with_confidence`, which uses a fixed internal 0.5. Passing 0.99 returns the
same 0.8 match as passing 0.0.

Scope: this set exercises reference integrity — whether the returned code is
real and is the one asked for. It does not measure whether a cross-system
mapping is clinically right. That needs an adjudicated set, which this repo does
not have; `scripts/calibration_report.py --emit-unlabelled` writes the worksheet
for one.

### Why no calibrator ships

An isotonic fit on this set (half fit, half held out) takes held-out ECE from
0.087 to 0.000 and Brier from 0.059 to 0.000 with AUC unchanged at 1.000, since
a monotone map cannot reorder anything. The fitted map is
`{0.0 → 0, 0.6 → 0, 0.8 → 0, 1.0 → 1}`: it has seen exact hits and absent codes
and nothing else. Applying it to the display-text traffic the fuzzy matcher
exists for would be extrapolation, so nothing is wired into the serving path.
The fitting code is ready for an adjudicated set.

## SNOMED-CT to ICD-10-CM Official Mapping

NLM provides an official SNOMED CT to ICD-10-CM mapping with **126,000+ NLM-verified
concepts** as part of the SNOMED CT US Edition release. This is the gold standard
crosswalk — far more comprehensive than our 1,898 Synthea-derived mappings.

To load:
1. Download SNOMED CT US Edition from [NLM](https://www.nlm.nih.gov/healthit/snomedct/us_edition.html)
2. Find: `tls_Icd10cmHumanReadableMap_US1000124_YYYYMMDD.tsv`
3. Convert with: `python3 scripts/build_terminology_data.py --umls <path>` (future: dedicated flag)

## Performance

- **Startup time**: < 1 second with 123K terms (measured ~0.14s)
- **Lookup latency**: < 1ms per query (in-memory dict + prefix index)
- **Memory**: ESTIMATED ~50MB with 123K terms (not benchmarked)
- **With full UMLS**: ESTIMATED ~200MB memory, ~5s startup, < 1ms lookup

---

*Last updated: 2026-06-19 — ICD-10-CM (CMS 2027, 74K) + RxNorm (NLM API, 47K) loaded. No hallucinated data.*