# Payer-Specific Rules

Each YAML file in this directory defines coding rules for a specific payer.
Hospitals can contribute rules they've learned from denial patterns.

## File Naming
`{payer_name}.yml` — e.g., `medicare.yml`, `medicaid_texas.yml`, `bcbs.yml`

## Rule Format
```yaml
payer: Medicare
rules:
  - code: "E11.9"
    system: ICD-10-CM
    checks:
      - type: requires_secondary
        message: "Diabetes codes require HbA1c lab (LOINC 4548-4) within 90 days"
      - type: excluded_with
        codes: ["E10.9"]
        message: "Cannot bill E11.9 with E10.9 (Type 1 and Type 2 diabetes mutually exclusive)"
  - code_system: ICD-10-CM
    code_pattern: "O*"
    checks:
      - type: gender_restriction
        allowed: F
        message: "Obstetric codes (O*) are female-only"
```

## Check Types
| Type | Description |
|------|-------------|
| `requires_secondary` | Must also have a specific code/system present |
| `excluded_with` | Cannot be billed with certain other codes |
| `gender_restriction` | Only valid for specific gender (M/F) |
| `age_restriction` | Only valid for age range (min-max) |
| `date_range` | Only valid during specific date range |
| `frequency_limit` | Maximum N occurrences per time period |
| `modifier_required` | CPT/HCPCS code requires specific modifier |

## Contributing
Submit rules via PR. Include the denial reason text from the payer's remittance advice.
