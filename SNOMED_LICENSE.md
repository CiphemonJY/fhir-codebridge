# SNOMED CT Licensing

fhir-codebridge uses SNOMED CT in two ways. This document explains what
is included, what requires a license, and how to comply.

## What's Included (No License Required)

fhir-codebridge ships with a **SNOMED CT problem-list subset** — a
curated list of commonly used clinical concepts for problem lists and
diagnostic coding. This subset is derived from publicly available
reference data published by the National Library of Medicine (NLM).

The pre-loaded subset contains approximately 6,000 concepts covering:
- Common diagnoses (diabetes, hypertension, heart failure, etc.)
- Common clinical findings (fever, pain, dyspnea, etc.)
- Common procedures and interventions
- Social determinants of health (Z-codes mapping)

**This subset is freely redistributable.** No SNOMED license is required
to use fhir-codebridge with the pre-loaded subset.

## What Requires a UMLS License

Full SNOMED CT (~350,000 concepts) requires a UMLS API key from the
National Library of Medicine. This is free but requires registration:

1. Register at https://uts.nlm.nih.gov/uts/signup
2. Use an organizational email (not Gmail/Yahoo)
3. Approval takes 1-2 business days
4. Add your API key to fhir-codebridge via env var or Docker secret

With a UMLS key, fhir-codebridge can:
- Look up any SNOMED CT concept via the UMLS REST API
- Load full SNOMED CT from a hospital-provided MRCONSO.RRF file
- Access cross-system mappings maintained by NLM

## SNOMED International Licensing

SNOMED CT is owned and maintained by SNOMED International. Different
countries have different licensing arrangements:

- **US:** SNOMED CT US Edition is available via UMLS (NLM). Free for
  use within the United States.
- **UK:** SNOMED CT is provided under license by NHS Digital. Free for
  use within the UK healthcare system.
- **Other countries:** Check https://www.snomed.org/snomed-ct/get-snomed-ct
  for your country's licensing terms.

fhir-codebridge does not redistribute full SNOMED CT. It provides:
1. A limited problem-list subset (freely redistributable)
2. An API integration that fetches SNOMED CT on-demand from UMLS
   (requires your UMLS key, terms are cached locally)

## Your Responsibilities

If you deploy fhir-codebridge in a production healthcare environment:

1. **Verify your SNOMED licensing** for your jurisdiction
2. **If using UMLS:** Ensure your UMLS API key usage complies with NLM terms
3. **If sharing derived data:** SNOMED CT content in crosswalk mappings
   may be subject to SNOMED International licensing terms
4. **Audit log:** SNOMED codes appearing in audit logs are metadata about
   API usage, not redistribution of SNOMED content

## Disclaimer

This document is for informational purposes only and does not constitute
legal advice. Consult your organization's legal counsel or compliance
officer regarding SNOMED CT licensing for your specific use case.

## References

- SNOMED International: https://www.snomed.org
- NLM UMLS: https://www.nlm.nih.gov/research/umls/
- UMLS licensing: https://www.nlm.nih.gov/research/umls/license.html
- SNOMED CT licensing FAQ: https://www.snomed.org/snomed-ct-faq