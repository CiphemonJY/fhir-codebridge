#!/usr/bin/env python3
"""
fhir-codebridge Python Client Example
=======================================
Minimal Python client for the fhir-codebridge terminology mapping API.

Usage:
    python3 client_example.py
"""

import requests
import json
import sys

BASE_URL = "http://localhost:8000"
API_KEY = "changeme-admin-key"  # Replace with your key
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


def health_check():
    """Check if the service is running."""
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    data = r.json()
    print(f"Status: {data['status']} | Terms: {data.get('terms_loaded', 0):,} | "
          f"UMLS: {data.get('umls_enabled', False)} | Auth: {data.get('auth_enabled', False)}")
    return data


def lookup_code(code, system, target_system=None):
    """Look up a code and optionally map to another system."""
    payload = {"code": code, "system": system}
    if target_system:
        payload["target_system"] = target_system
    
    r = requests.post(f"{BASE_URL}/lookup", json=payload, headers=HEADERS, timeout=10)
    return r.json()


def lookup_display(text, target_system=None):
    """Look up a code by display text (fuzzy match)."""
    payload = {"display": text}
    if target_system:
        payload["target_system"] = target_system
    
    r = requests.post(f"{BASE_URL}/lookup", json=payload, headers=HEADERS, timeout=10)
    return r.json()


def fhir_translate(code, system_uri, target_uri=None):
    """FHIR ConceptMap $translate operation."""
    payload = {"code": code, "system": system_uri}
    if target_uri:
        payload["target_system"] = target_uri
    
    r = requests.post(f"{BASE_URL}/$translate", json=payload, headers=HEADERS, timeout=10)
    return r.json()


def get_stats():
    """Get terminology coverage statistics."""
    r = requests.get(f"{BASE_URL}/stats", headers=HEADERS, timeout=5)
    return r.json()


def query_audit(limit=50, action=None):
    """Query the audit log (admin only)."""
    params = {"limit": limit}
    if action:
        params["action"] = action
    r = requests.get(f"{BASE_URL}/audit", params=params, headers=HEADERS, timeout=10)
    return r.json()


if __name__ == "__main__":
    print("=== fhir-codebridge Python Client ===\n")
    
    # 1. Health check
    print("1. Health Check")
    try:
        health_check()
    except requests.exceptions.ConnectionError:
        print("   ERROR: Service not running. Start with: docker-compose up -d")
        sys.exit(1)
    print()
    
    # 2. Stats
    print("2. Terminology Statistics")
    stats = get_stats()
    for system, count in sorted(stats.get("by_system", {}).items(), key=lambda x: -x[1]):
        print(f"   {system:<15} {count:>7,}")
    print()
    
    # 3. Lookup ICD-10 → SNOMED
    print("3. Lookup: E11.9 (ICD-10-CM) → SNOMED-CT")
    result = lookup_code("E11.9", "ICD-10-CM", "SNOMED-CT")
    print(f"   Action: {result['action']} | Confidence: {result['effective_confidence']:.1%}")
    if result.get("source"):
        print(f"   Source: {result['source']['display']}")
    for t in result.get("targets", [])[:3]:
        print(f"   → {t['system']}|{t['code']} — {t['display']} ({t['confidence']:.1%})")
    print()
    
    # 4. Fuzzy lookup
    print("4. Fuzzy Lookup: 'htn' → ICD-10-CM")
    result = lookup_display("htn", "ICD-10-CM")
    print(f"   Action: {result['action']} | Confidence: {result['effective_confidence']:.1%}")
    if result.get("source"):
        print(f"   Source: {result['source']['system']}|{result['source']['code']} — {result['source']['display']}")
    print()
    
    # 5. FHIR $translate
    print("5. FHIR $translate: E11.9 ICD-10-CM → SNOMED-CT")
    result = fhir_translate(
        "E11.9",
        "http://hl7.org/fhir/sid/icd-10-cm",
        "http://snomed.info/sct"
    )
    for param in result.get("parameter", []):
        if param.get("name") == "result":
            print(f"   Result: {param.get('valueBoolean')}")
        if param.get("name") == "match":
            parts = {p["name"]: p.get("valueCode") or p.get("valueString") or p.get("valueDecimal") 
                     for p in param.get("part", [])}
            print(f"   Match: {parts.get('code')} — {parts.get('display')} "
                  f"(confidence: {parts.get('confidence')})")
    print()
    
    # 6. Audit log
    print("6. Recent Audit Log Entries (last 5)")
    audit = query_audit(limit=5)
    for entry in audit.get("entries", []):
        print(f"   {entry['ts']} | {entry['action']:10} | {entry['detail'].get('code', '?')}")
    print()
    
    print("Done. See examples/curl_examples.sh for more.")