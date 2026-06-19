#!/bin/bash
# fhir-codebridge API Examples — curl
# Run these after `docker-compose up -d` (or uvicorn locally)
# Replace API_KEY with your admin key, or remove -H header if auth disabled.

API_KEY="${API_KEY:-changeme-admin-key}"
BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "=== 1. Health Check ==="
curl -s "$BASE_URL/health" | python3 -m json.tool
echo ""

echo "=== 2. Service Statistics ==="
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/stats" | python3 -m json.tool
echo ""

echo "=== 3. Loaded Coding Systems ==="
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/systems" | python3 -m json.tool
echo ""

echo "=== 4. Lookup ICD-10-CM Code (E11.9 = Type 2 Diabetes) ==="
curl -s -X POST "$BASE_URL/lookup" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"code": "E11.9", "system": "ICD-10-CM", "target_system": "SNOMED-CT"}' | python3 -m json.tool
echo ""

echo "=== 5. Lookup by Display Text (metformin) ==="
curl -s -X POST "$BASE_URL/lookup" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"display": "metformin", "target_system": "RXNORM"}' | python3 -m json.tool
echo ""

echo "=== 6. FHIR $translate Operation ==="
curl -s -X POST "$BASE_URL/\$translate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "code": "E11.9",
    "system": "http://hl7.org/fhir/sid/icd-10-cm",
    "target_system": "http://snomed.info/sct"
  }' | python3 -m json.tool
echo ""

echo "=== 7. Lookup RxNorm Drug Code ==="
curl -s -X POST "$BASE_URL/lookup" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"code": "860975", "system": "RXNORM"}' | python3 -m json.tool
echo ""

echo "=== 8. Lookup CDT Dental Code ==="
curl -s -X POST "$BASE_URL/lookup" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"code": "D0120", "system": "CDT"}' | python3 -m json.tool
echo ""

echo "=== 9. Query Audit Log (admin only) ==="
curl -s -H "X-API-Key: $API_KEY" "$BASE_URL/audit?limit=5" | python3 -m json.tool
echo ""

echo "=== 10. Fuzzy Match — Common Abbreviation ==="
curl -s -X POST "$BASE_URL/lookup" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"display": "htn", "target_system": "ICD-10-CM"}' | python3 -m json.tool
echo ""

echo "Done. See INSTALL.md for deployment details."