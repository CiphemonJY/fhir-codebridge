# Benchmark & Calibration

## Current Data Coverage

### Shipped Data (Verified Sources Only)

| System | Count | Source | Full Set Size | Coverage |
|--------|-------|--------|---------------|----------|
| ICD-10-CM | 74,879 | CMS 2027 (public domain) | ~74,879 | 100% |
| RxNorm | 47,780 | NLM RxNorm REST API (public domain) | ~80,000 (est.) | ~59% (est.) |
| CDT | 397 | Project source TSV | 397 | 100% |
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

### Exact code lookup

When a code exists in the loaded terminology it is returned at confidence 1.0 by
direct index lookup, with no model in the path. Measured 600/600 on the
membership-labelled set described under Calibration.

```
Input:  ICD-10-CM|E11.9
Output: auto_accept @ 100.0% — "Type 2 diabetes mellitus without complications"
Method: exact_code_lookup
```

### Crosswalk mappings

The 1,898 crosswalk mappings were generated through Synthea patient data analysis
with cosine similarity scoring against the db_523 ontology. These are computed (not manually reviewed)
mappings, not hallucinated.

### Fuzzy text matching — coverage

Which systems can be searched by display text, and over how many terms. This is
coverage, not accuracy: for what a fuzzy match is worth once returned, see
Calibration below, which measures it.

- **ICD-10-CM**: Search by diagnosis description → find code (works for 74K+ terms)
- **RxNorm**: Search by drug name → find RxNorm code (works for 47K+ terms)
- **CDT**: Search by procedure name → find CDT code (works for all 397 terms)
- **LOINC**: Limited to 23 core terms until UMLS/LOINC registration

### Neural Model (Experimental)

The DP-LoRA fine-tuned model (experimental neural cross-system mapping) provides neural cross-system
mapping for codes NOT in the RAG layer. This is the experimental layer — 64.8%
accuracy on unseen code pairs.

**Architecture**: exact index lookup → neural model for codes it does not hold → human review

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
in `map_with_confidence`, and the `threshold` argument on `CodeBridge.lookup()`
and `LookupRequest`, which sets the minimum similarity a fuzzy display match
must reach — so it is measured on its own.

- Metrics: `codebridge/calibration.py` — ECE, Brier, reliability table with
  Wilson intervals, AUC, isotonic (PAV) and Platt calibrators. Standard library
  only, so it imports wherever the service runs.
- Report: `python3 scripts/calibration_report.py --labels <set.jsonl>`

Two labelled sets are used, because neither one alone reaches every decision the
router makes. Both derive their labels from the data rather than from clinical
judgement, and both say so about their own limits.

### Measured on a membership-labelled set

Labels here follow from terminology membership, which is a fact about the loaded
data rather than a clinical judgement: a code present in a loaded system has
exactly one correct entry, and a code present in no loaded system has no correct
mapping at all, so any mapping returned for it is wrong. Built with
`scripts/calibration_report.py --build-membership-set`, seed 11, 600 positives
(codes and display strings drawn from the index) and 600 negatives (codes
verified absent from every loaded system under every code variant the lookup
tries). Shipped data only, 123,079 terms, no UMLS.

| Confidence (mean) | n | Observed accuracy | 95% CI (Wilson) |
|---|---|---|---|
| 0.000 | 600 | 0/600 = 0.000 | 0.000 – 0.006 |
| 1.000 | 600 | 600/600 = 1.000 | 0.994 – 1.000 |

ECE 0.000, MCE 0.000, Brier 0.000, AUC 1.000 (10 equal-frequency bins requested,
2 used — the score takes only two distinct values on this set).

Read that with care. It is not evidence that the score is a good probability; it
is evidence that this set only asks the score to separate "the code exists" from
"it does not", which it does exactly. Every row lands at 1.0 or 0.0, so the
0.60–0.95 band the review threshold governs is empty here and this set says
nothing about it. That band is what the perturbation set below is for.

Scope: this set exercises reference integrity — whether the returned code is
real and is the one asked for. It does not measure whether a cross-system
mapping is clinically right. That needs an adjudicated set, which this repo does
not have; `scripts/calibration_report.py --emit-unlabelled` writes the worksheet
for one.

### Measured on a perturbation-labelled set

The membership set cannot reach the fuzzy display matcher, because a code that is
present exits at an exact hit and a code that is absent has no right answer.
This set reaches it: take a term that IS in the terminology, vary how it is
written, and ask for it by display text. The correct answer is known by
construction — the entry the string came from — so the labels are still derived
rather than judged. Built with
`scripts/calibration_report.py --build-perturbation-set`, seed 7, 700 rows, of
which 546 carry derived labels.

Grouped on fixed cutpoints so the rows sum to the 546 labelled rows (the report
itself prints 10 equal-frequency bins):

| Confidence range | n | Observed accuracy | 95% CI (Wilson) | Mean confidence |
|---|---|---|---|---|
| 0.000 – 0.912 | 56 | 22/56 = 0.393 | 0.276 – 0.524 | 0.683 |
| 0.912 – 0.970 | 58 | 55/58 = 0.948 | 0.859 – 0.982 | 0.951 |
| 0.970 – 0.980 | 54 | 52/54 = 0.963 | 0.875 – 0.990 | 0.975 |
| 0.980 – 1.000 | 300 | 300/300 = 1.000 | 0.987 – 1.000 | 0.991 |
| 1.000 | 78 | 78/78 = 1.000 | 0.953 – 1.000 | 1.000 |

ECE 0.037, MCE 0.296, Brier 0.036, AUC 0.981, all 10 bins populated. Accuracy in
the `review` band (0.70–0.95) is 61 rows at 0.672 [0.547, 0.777].

Two things are visible here that the membership set hides. From roughly 0.91 up
the score tracks accuracy closely. Below that it is materially overconfident —
the bottom group averages 0.683 confidence against 0.393 observed accuracy, a gap
of +0.29, which is where the MCE comes from. AUC is 0.981 rather than 1.000, so
on this traffic the score does not rank perfectly either.

Accuracy also varies by how the term was rewritten, and the pooled number hides
the spread:

| Perturbation | n | Mean confidence | Accuracy | 95% CI (Wilson) |
|---|---|---|---|---|
| word_reorder | 78 | 0.845 | 0.705 | 0.596 – 0.795 |
| typo_swap | 78 | 0.934 | 0.923 | 0.842 – 0.964 |
| typo_dup | 78 | 0.964 | 0.949 | 0.875 – 0.980 |
| typo_drop | 78 | 0.965 | 0.949 | 0.875 – 0.980 |
| punct_strip | 78 | 0.985 | 0.974 | 0.911 – 0.993 |
| whitespace | 78 | 0.990 | 1.000 | 0.953 – 1.000 |
| case_flip | 78 | 1.000 | 1.000 | 0.953 – 1.000 |

A transposed word is the weakest case: 0.705 accuracy carried at 0.845 mean
confidence. Case, whitespace and punctuation changes are absorbed cleanly.

Scope: this set measures whether display retrieval survives how a term is
written. It does not measure clinical correctness either. Perturbations that
remove content — `word_drop`, `truncate` — can name a genuinely different real
concept, so their 154 rows are emitted with `correct: null` and are excluded from
every number above; they are a worksheet for a terminologist, not a label.

### Why no calibrator ships

Fitting isotonic on the perturbation set (half fit, half held out) lowers ECE
from 0.047 to 0.026 and Brier from 0.042 to 0.024, and lowers AUC from 0.975 to
0.940 — a monotone map cannot improve ranking, and this one loses some by merging
distinct scores into ties. So a calibrator here buys better-behaved numbers at a
measurable cost to discrimination, on a set built from synthetic surface
variation rather than real traffic. Nothing is wired into the serving path;
`effective_confidence` is the raw reading everywhere. The fitting code is ready
for a set drawn from real queries, or for the 154 rows above once adjudicated.

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