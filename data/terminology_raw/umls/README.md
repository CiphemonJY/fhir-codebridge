# UMLS Data Directory

Place your hospital's UMLS Metathesaurus files here.

## Quick Start

1. **Get a UMLS License** (free for US users):
   - Register at https://www.nlm.nih.gov/research/umls/license/license.html
   - Request a UMLS Terminology Services (UTS) account

2. **Download the Metathesaurus**:
   - Log in to https://uts.nlm.nih.gov/uts/
   - Download the latest Metathesaurus release
   - Extract the archive

3. **Place MRCONSO.RRF here**:
   ```bash
   cp /path/to/extracted/umls/META/MRCONSO.RRF ./MRCONSO.RRF
   ```

4. **Restart the server** — the RAG engine auto-detects and loads it.

## What This File Provides

A single `MRCONSO.RRF` file contains **all** of the following:
- SNOMED-CT US Edition (~350K concepts)
- ICD-10-CM (~74K codes)
- LOINC (~90K codes)
- RxNorm (~81K codes)
- CPT, CVX, and 200+ other vocabularies

That's **600K+ sourced terminology entries** from one file.

## File Format

`MRCONSO.RRF` is a pipe-delimited file with one concept per line.
The RAG engine parses:
- Column 1: CUI (Concept Unique Identifier)
- Column 2: LAT (Language — only ENG loaded)
- Column 7: ISPREF (only preferred terms loaded)
- Column 12: SAB (Source Abbreviation — determines system)
- Column 13: TTY (Term Type)
- Column 14: CODE (Code in source system)
- Column 15: STR (String/Display name)
- Column 17: SUPPRESS (suppressed entries skipped)

## License

Use of UMLS data requires compliance with the [UMLS License Agreement](https://www.nlm.nih.gov/research/umls/license/license.html).
You are responsible for ensuring your use complies with all source vocabulary licenses
(SNOMED-CT, LOINC, CDT, etc.) as described in the UMLS License.

## Alternative: Individual System Files

If you don't have a full UMLS license but have individual registrations,
use the build script to convert individual downloads:

```bash
python3 scripts/build_terminology_data.py --help
```

See `data/terminology_parsed/README.md` for per-system instructions.