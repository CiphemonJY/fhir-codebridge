# Healthcare Terminology Glossary

*A quick reference for fhir-codebridge users.*

## Coding Systems

### ICD-10-CM
**Full name:** International Classification of Diseases, 10th Revision, Clinical Modification
**Publisher:** CMS (public domain)
**Use:** Diagnosis coding for billing and quality reporting
**Update cadence:** October 1 annually
**Example:** `E11.9` = Type 2 diabetes mellitus without complications

### SNOMED-CT
**Full name:** Systematized Nomenclature of Medicine — Clinical Terms
**Publisher:** NLM (US Edition, requires affiliate license)
**Use:** Clinical documentation, problem lists, EHR
**Update cadence:** Biannually (March/September)
**Example:** `73211009` = Diabetes mellitus

### LOINC
**Full name:** Logical Observation Identifiers Names and Codes
**Publisher:** Regenstrief Institute (free registration required)
**Use:** Lab tests, clinical observations, measurements
**Update cadence:** Semi-annually (June/December)
**Example:** `2339-0` = Glucose [Mass/volume] in Blood

### RxNorm
**Full name:** RxNorm
**Publisher:** NLM (public domain)
**Use:** Clinical drug names, medication reconciliation
**Update cadence:** Monthly
**Example:** `860975` = Metformin 500 MG Oral Tablet

### CDT
**Full name:** Current Dental Terminology
**Publisher:** American Dental Association (copyright, license required)
**Use:** Dental procedure coding
**Update cadence:** Annually (usually Q4)
**Example:** `D0120` = Periodic oral evaluation

## Standards

### FHIR
Fast Healthcare Interoperability Resources — HL7's modern API standard for healthcare data exchange.

### HL7 v2
Health Level 7 version 2 — pipe-and-hat message format used by most EHRs for ADT (admission, discharge, transfer) feeds.

### ConceptMap $translate
A FHIR operation that translates a code from one system to another. fhir-codebridge implements this at `POST /$translate`.

## Terms

### Crosswalk
A mapping table between two coding systems. Example: ICD-10-CM `E11.9` maps to SNOMED-CT `73211009`.

### Provenance
Metadata showing where a mapping came from and how it was computed. Required for audit compliance.

### Token bucket
A rate limiting algorithm. fhir-codebridge uses it to prevent API abuse.

### UMLS Metathesaurus
NLM's comprehensive terminology database. Contains 600K+ concepts across all systems. Requires free UMLS license.
