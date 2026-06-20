# Claim Verification Guidelines

All factual claims in this repository must be verifiable. This document
defines what counts as a claim, what counts as verification, and how to
prevent unverified claims from entering the repo.

## What Is a Claim?

Any statement that could be checked against reality:

- **Numbers**: term counts, performance metrics, latency, memory, file sizes
- **Comparisons**: "faster than X", "better than Y", "the only Z that..."
- **Compliance**: "HIPAA compliant", "FDA cleared", "certified"
- **Competitor statements**: deployment times, feature lists, pricing
- **Provenance**: "data from CMS", "verified mappings", "official source"
- **Performance**: "startup in X seconds", "handles Y requests/second"

## What Is NOT a Claim?

- Descriptions of what the code does (read the code to verify)
- Instructions and usage examples (test them to verify)
- Opinions clearly marked as such ("we recommend", "in our experience")
- Aspirational roadmap items marked as TODO/planned

## Verification Tiers

| Tier | Label | Requirement |
|------|-------|-------------|
| **Verified** | `verified` | Measured or fetched in this session. Cite source. |
| **Estimated** | `ESTIMATED` | Based on partial data. State methodology. |
| **Cited** | `[source]` | From a named source. Include link or reference. |
| **Unverified** | — | Do NOT include in docs. Say "not measured" instead. |

## Rules

1. **No compliance claims.** Don't say "HIPAA compliant" or "certified."
   Say "implements [specific requirement]" or "designed to support [standard]."
2. **No competitor comparisons.** Don't compare to named products.
   Use "What This Is / What This Is Not" positioning instead.
3. **No performance numbers without measurement.** If you claim "X seconds,"
   you must have timed it. Label estimates as ESTIMATED with methodology.
4. **No "verified" without a source.** If you say "verified," cite the source.
5. **No deployment time claims.** "5 minutes", "in minutes", etc. depend on
   the user's environment. Say "Docker-deployable" without a time claim.
6. **Payer rules are samples.** Label all shipped payer rules as illustrative
   samples, not official policy.
7. **Data counts must match `stats()` output.** Run the service, check
   `/stats`, use that number. Don't hardcode counts in documentation.

## Pre-Commit Checklist

Before committing documentation changes:

- [ ] Every number is verified or labeled ESTIMATED
- [ ] No compliance certification claims (HIPAA compliant, certified, etc.)
- [ ] No competitor comparison tables
- [ ] No performance claims without measurement
- [ ] Payer rules labeled as samples
- [ ] Term counts match `GET /stats` output
- [ ] No "verified" labels without cited source
- [ ] No unverified competitor claims (deployment times, features, pricing)

## CI Gate

The `scripts/check_claims.py` script runs in CI and flags potential
unverified claims for review. See `.github/workflows/ci.yml`.

## Reporting Issues

If you find an unverified claim in the repo, open an issue with:
1. The file and line number
2. The claim text
3. Why it's unverified
4. Suggested fix (remove, verify, or label as estimated)
