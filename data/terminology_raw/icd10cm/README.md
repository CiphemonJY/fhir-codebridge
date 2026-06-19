# ICD-10-CM Raw Data (CMS Download)

ICD-10-CM code descriptions are downloaded from CMS.gov (public domain, no license required).

## How to load

1. Download from [CMS ICD-10-CM](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
2. Get the "Code Descriptions in Tabular Order" ZIP file
3. Extract the `icd10cm_codes_YYYY.txt` file
4. Run: `python3 scripts/build_terminology_data.py --icd10cm <path-to-txt>`

The parsed JSON (`data/terminology_parsed/icd10cm_full.json`) ships with the repo and
contains 74,879 codes from the CMS 2027 release.

## Source

- **URL:** https://www.cms.gov/medicare/coding-billing/icd-10-codes
- **License:** Public domain (US government work)
- **Update frequency:** Annually (October) + mid-year updates (April)
- **Format:** Tab-separated text file (code + description)