# Terminology Data Directory

This directory contains the terminology data files used by the RAG lookup engine.

## Shipped Data (Sourced)

These files are included with the project and contain verified data from project sources:

| File | System | Count | Source |
|------|--------|-------|--------|
| `icd10cm_full.json` | ICD-10-CM | 74,879 | CMS 2027 code descriptions (public domain) |
| `rxnorm.json` | RxNorm | 47,780 | NLM RxNorm REST API (public domain) + project TSV |
| `cdt.json` | CDT | 397 | CDT source TSV (current dental terminology) |
| `loinc_core.json` | LOINC | 23 | Core LOINC vital signs (from project data) |
| `db523_ontology.json` | LOINC + RxNorm | 523 | Combined ontology (db_523 project data) |
| `crosswalk_v3.json` | Crosswalk | 1,898 | Synthea-derived cross-system similarity mappings |

**Total: 123,079 sourced entries — no hallucinated data.**

### Data Sources

- **CMS ICD-10-CM**: Public domain, freely redistributable. Downloaded from [CMS.gov](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
- **NLM RxNorm API**: Public domain. Retrieved via [RxNorm REST API](https://rxnav.nlm.nih.gov/)
- **CDT**: Project source data (ADA license required for redistribution in commercial products)
- **LOINC**: Project source subset. Full set requires free registration at [loinc.org](https://loinc.org/)
- **Crosswalk**: Generated from Synthea synthetic patient data using embedding cosine similarity scoring

## Hospital-Provided Data (Placeholders)

These files are **NOT included** — hospitals must provide them using their UMLS license
or free registrations. The system is designed to work with whatever data is available
and scales automatically when more data is loaded.

### How to Load Full Terminology Data

#### Option 1: UMLS Metathesaurus (MRCONSO.RRF)

If your hospital has a UMLS license (free for US users via [NLM UMLS](https://www.nlm.nih.gov/research/umls/)):

1. Download the UMLS Metathesaurus from the [UTS Download Page](https://uts.nlm.nih.gov/uts/)
2. Extract `MRCONSO.RRF` from the archive
3. Place it in `data/terminology_raw/umls/MRCONSO.RRF`
4. Restart the server — the RAG engine auto-loads all available terminology systems

This single file provides:
- SNOMED-CT (~350K concepts)
- ICD-10-CM (~74K codes)
- LOINC (~90K codes)
- RxNorm (~81K codes)
- CPT, CVX, and 200+ other vocabularies

#### Option 2: Individual System Downloads

If you only need specific systems:

##### SNOMED-CT US Edition
- Register at [NLM SNOMED CT](https://www.nlm.nih.gov/healthit/snomedct/us_edition.html)
- Download the US Edition release
- Convert to JSON format using `scripts/build_terminology_data.py --umls <path>`
- Output: `snomed_ct.json` in this directory

##### SNOMED-CT to ICD-10-CM Mapping
- Available with the SNOMED CT US Edition download
- File: `tls_Icd10cmHumanReadableMap_US1000124_YYYYMMDD.tsv`
- Over 126,000 NLM-verified SNOMED → ICD-10-CM mappings
- Convert: `scripts/build_terminology_data.py --snomed-icd10-map <path>`

##### ICD-10-CM
- Download from [CMS.gov](https://www.cms.gov/Medicare/Coding/ICD10) (public domain)
- File: `ICD-10-CM-Code-Tables.zip`
- Convert: `scripts/build_terminology_data.py --icd10cm <path>`

##### LOINC
- Register at [loinc.org](https://loinc.org/) (free)
- Download the LOINC release (multiaxial hierarchy + text files)
- Convert: `scripts/build_terminology_data.py --loinc <path>`

##### RxNorm
- Download from [NLM RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/) (public domain)
- File: `RxNorm_full_current.zip`
- Convert: `scripts/build_terminology_data.py --rxnorm <path>`

## Data Format

All JSON files use the same format:

```json
[
  {
    "code": "E11.9",
    "system": "ICD-10-CM",
    "display": "Type 2 diabetes mellitus without complications"
  }
]
```

## RAG Engine Auto-Discovery

The RAG engine (`scripts/rag/rag_lookup.py`) automatically:
1. Loads all `.json` files in this directory
2. Deduplicates entries by `system|code`
3. Builds lookup indexes (exact code + fuzzy display)
4. Loads crosswalk mappings from `crosswalk_v3.json`
5. If `data/terminology_raw/umls/MRCONSO.RRF` exists, loads it (adds 500K+ terms)

No configuration needed — just drop files in and restart.

## License Notes

- **Software code**: MIT License (see `LICENSE`)
- **SNOMED-CT**: Requires [IHTSDO Affiliate License](https://www.snomed.org/) — free for US users via NLM
- **LOINC**: Requires [free registration](https://loinc.org/) at Regenstrief Institute
- **ICD-10-CM**: Public domain (CMS/WHO)
- **RxNorm**: Public domain (NLM)
- **CDT**: © American Dental Association — requires [ADA license](https://www.ada.org/en/publications/cdt)
- **UMLS Metathesaurus**: Requires [NLM UMLS license](https://www.nlm.nih.gov/research/umls/license/license.html)

See `SNOMED_LICENSE.md` for SNOMED-CT licensing details.