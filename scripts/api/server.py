#!/usr/bin/env python3
"""
fhir-codebridge FHIR Terminology Service
=========================================
FastAPI server wrapping the RAG lookup engine.

Endpoints:
  GET  /health              — service status
  GET  /stats               — terminology coverage stats
  POST /lookup              — code lookup + cross-system mapping
  POST /$translate          — FHIR-compatible ConceptMap $translate operation
  GET  /systems             — list loaded coding systems
  GET  /audit               — query audit log (requires admin key)

Security:
  - API key auth via LISA_API_KEYS env var (comma-separated)
  - RBAC: admin keys can query audit log, read-only keys can use lookup/translate
  - Audit log: every request logged to data/audit.log
  - UMLS proxy: rate-limited + cached (guardrail against API abuse)

Run:
  uvicorn scripts.api.server:app --host 0.0.0.0 --port 8000
"""

import os
import sys
import json
import time
import secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from typing import Optional

# Add parent to path so we can import rag_lookup
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.rag_lookup import RAGLookup


# --- Docker secrets support ---
# Read secret from file if _FILE env var is set, else from env var directly

def _read_secret(name: str) -> str:
    """Read a secret from env var or Docker secret file."""
    file_var = f"{name}_FILE"
    file_path = os.environ.get(file_var)
    if file_path and os.path.exists(file_path):
        with open(file_path) as f:
            return f.read().strip()
    return os.environ.get(name, "")

# --- Config ---
API_KEYS_ENV = _read_secret("LISA_API_KEYS")
# Format: "key1:admin,key2:read,key3:read" or just "key1" (defaults to admin)
API_KEYS: dict[str, str] = {}  # key → role
if API_KEYS_ENV:
    for entry in API_KEYS_ENV.split(","):
        entry = entry.strip()
        if ":" in entry:
            k, role = entry.split(":", 1)
            API_KEYS[k.strip()] = role.strip().lower()
        else:
            API_KEYS[entry] = "admin"

# Auth: enabled if API keys are set OR if explicit auth-disabled flag is not set
# Safety: must explicitly set LISA_AUTH_DISABLED=1 to run without auth
AUTH_EXPLICITLY_DISABLED = os.environ.get("LISA_AUTH_DISABLED", "").strip() in ("1", "true", "yes")
AUTH_ENABLED = bool(API_KEYS) or not AUTH_EXPLICITLY_DISABLED
if AUTH_EXPLICITLY_DISABLED and not API_KEYS:
    print("WARNING: LISA_AUTH_DISABLED=1 — API is running in open mode (no authentication). "
          "Do NOT use in production.")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Audit log path
AUDIT_LOG = Path(os.environ.get("LISA_AUDIT_LOG", "data/audit.log"))
AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

# --- Init ---
app = FastAPI(
    title="fhir-codebridge FHIR Terminology Service",
    description="Open source on-prem terminology mapper. Bring your UMLS API key for full coverage.",
    version="0.2.0",
)

# CORS: configurable via env var, defaults to restrictive (no wildcard + credentials)
CORS_ORIGINS = os.environ.get("LISA_CORS_ORIGINS", "").strip()
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in CORS_ORIGINS.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )
# No CORS middleware if LISA_CORS_ORIGINS not set = same-origin only (most secure)

# Load RAG engine once at startup
rag = RAGLookup()


# --- Audit Logging ---

def audit_log(request: Request, action: str, detail: dict):
    """Append a JSON line to the audit log. Fire-and-forget."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        "ip": request.client.host if request.client else "",
        "endpoint": str(request.url.path),
        "detail": detail,
    }
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        # Log to stderr — audit failures should be visible, not silent
        import sys as _sys
        print(f"AUDIT LOG ERROR: {e}", file=_sys.stderr)


# --- Auth + RBAC ---

async def get_api_key(request: Request, key: str = Security(API_KEY_HEADER)):
    """Validate API key. Returns role or raises 401/403."""
    if not AUTH_ENABLED:
        return "admin"  # Only reached if LISA_AUTH_DISABLED=1 is explicitly set
    if not key:
        raise HTTPException(401, "Missing API key. Set X-API-Key header.")
    role = API_KEYS.get(key)
    if not role:
        raise HTTPException(401, "Invalid API key.")
    audit_log(request, "auth", {"role": role})
    return role


async def require_admin(role: str = Depends(get_api_key)):
    """Require admin role for sensitive endpoints."""
    if AUTH_ENABLED and role != "admin":
        raise HTTPException(403, "Admin access required.")
    return role


# --- Models ---

class LookupRequest(BaseModel):
    code: Optional[str] = Field(None, description="Code to look up (e.g. 'E11.9')")
    system: Optional[str] = Field(None, description="Coding system (e.g. 'ICD-10-CM')")
    display: Optional[str] = Field(None, description="Display text to search (e.g. 'metformin')")
    target_system: Optional[str] = Field(None, description="Map to this system (e.g. 'SNOMED-CT')")
    threshold: float = Field(0.6, description="Minimum confidence for fuzzy matches (0.0-1.0)")


class MappingTarget(BaseModel):
    code: str
    system: str
    display: str
    confidence: float
    method: str


class LookupResponse(BaseModel):
    found: bool
    source: Optional[dict] = None
    targets: list[MappingTarget] = []
    action: str
    effective_confidence: float
    requires_human_review: bool


class FhirTranslateRequest(BaseModel):
    """FHIR ConceptMap $translate operation parameters."""
    code: str = Field(..., description="Source code")
    system: str = Field(..., description="Source system URI or name")
    target_system: Optional[str] = Field(None, description="Target system URI or name")
    source: Optional[str] = Field(None, description="ConceptMap source (ignored, we use all)")
    target: Optional[str] = Field(None, description="ConceptMap target (ignored)")


class FhirTranslateResponse(BaseModel):
    """FHIR-compatible $translate response."""
    resourceType: str = "Parameters"
    parameter: list[dict]


# --- FHIR system URI mapping ---
FHIR_SYSTEM_MAP = {
    "http://hl7.org/fhir/sid/icd-10-cm": "ICD-10-CM",
    "http://hl7.org/fhir/sid/icd-10": "ICD-10-CM",
    "http://snomed.info/sct": "SNOMED-CT",
    "http://loinc.org": "LOINC",
    "http://www.nlm.nih.gov/research/umls/rxnorm": "RXNORM",
    "http://www.ada.org/cdt": "CDT",
    "https://www.ada.org/cdt": "CDT",
    "urn:oid:2.16.840.1.113883.6.88": "RXNORM",
    "urn:oid:2.16.840.1.113883.6.90": "ICD-10-CM",
    "urn:oid:2.16.840.1.113883.6.96": "SNOMED-CT",
    "urn:oid:2.16.840.1.113883.6.1": "LOINC",
    "urn:oid:2.16.840.1.113883.6.13": "CDT",
    # Also accept plain names
    "ICD-10-CM": "ICD-10-CM",
    "SNOMED-CT": "SNOMED-CT",
    "LOINC": "LOINC",
    "RXNORM": "RXNORM",
    "CDT": "CDT",
    "CPT": "CPT",
}

REVERSE_FHIR_MAP = {v: k for k, v in FHIR_SYSTEM_MAP.items() if k.startswith("http")}


def normalize_system(s: str) -> str:
    """Accept FHIR URIs, OIDs, or plain names → internal system name."""
    if not s:
        return s
    return FHIR_SYSTEM_MAP.get(s, FHIR_SYSTEM_MAP.get(s.upper(), s))


# --- Endpoints ---

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "fhir-codebridge FHIR Terminology Service",
        "version": "0.2.0",
        "terms_loaded": len(rag.by_code),
        "umls_enabled": rag.umls_loaded,
        "auth_enabled": AUTH_ENABLED,
    }


@app.get("/stats")
async def stats(role: str = Depends(get_api_key)):
    return rag.stats()


@app.get("/systems")
async def systems(role: str = Depends(get_api_key)):
    s = rag.stats()
    return {
        "systems": [
            {"name": name, "count": count, "fhir_uri": REVERSE_FHIR_MAP.get(name)}
            for name, count in sorted(s["by_system"].items(), key=lambda x: -x[1])
        ],
        "total_terms": s["total_terms"],
        "crosswalk_mappings": s["crosswalk_mappings"],
        "umls_loaded": s["umls_loaded"],
        "gaps": s["gaps"],
    }


@app.post("/lookup", response_model=LookupResponse)
async def lookup(req: LookupRequest, request: Request, role: str = Depends(get_api_key)):
    """Look up a code or display text, optionally mapping to a target system."""
    system = normalize_system(req.system) if req.system else None
    target = normalize_system(req.target_system) if req.target_system else None
    
    result = rag.map_with_confidence(
        code=req.code,
        system=system,
        display=req.display,
        target_system=target,
    )
    
    audit_log(request, "lookup", {
        "code": req.code,
        "system": system,
        "display": req.display,
        "target": target,
        "found": result["found"],
        "action": result["action"],
        "confidence": result["effective_confidence"],
    })
    
    return result


@app.post("/$translate")
async def fhir_translate(req: FhirTranslateRequest, request: Request, role: str = Depends(get_api_key)):
    """
    FHIR ConceptMap $translate operation.
    Maps a code from one system to another.
    """
    source_sys = normalize_system(req.system)
    target_sys = normalize_system(req.target_system) if req.target_system else None
    
    result = rag.map_with_confidence(
        code=req.code,
        system=source_sys,
        target_system=target_sys,
    )
    
    audit_log(request, "translate", {
        "code": req.code,
        "system": source_sys,
        "target": target_sys,
        "found": result["found"],
    })
    
    # Build FHIR Parameters response
    params = []
    
    if result["found"]:
        params.append({
            "name": "result",
            "valueBoolean": True,
        })
        params.append({
            "name": "source",
            "valueUri": REVERSE_FHIR_MAP.get(source_sys, source_sys),
        })
        if result.get("source"):
            params.append({
                "name": "sourceCode",
                "valueCode": result["source"]["code"],
            })
            params.append({
                "name": "sourceDisplay",
                "valueString": result["source"]["display"],
            })
    
    for t in result.get("targets", []):
        match = {
            "name": "match",
            "part": [
                {"name": "equivalence", "valueCode": "equal" if t["confidence"] >= 0.95 else "wider"},
                {"name": "target", "valueUri": REVERSE_FHIR_MAP.get(t["system"], t["system"])},
                {"name": "code", "valueCode": t["code"]},
                {"name": "display", "valueString": t["display"]},
                {"name": "confidence", "valueDecimal": round(t["confidence"], 4)},
                {"name": "method", "valueString": t["method"]},
            ]
        }
        params.append(match)
    
    if not result["found"] and not result.get("targets"):
        params.append({"name": "result", "valueBoolean": False})
        params.append({"name": "message", "valueString": "No mapping found"})
    
    return {"resourceType": "Parameters", "parameter": params}


@app.get("/audit")
async def query_audit(
    request: Request,
    limit: int = Query(100, ge=1, le=10000),
    action: Optional[str] = Query(None),
    role: str = Depends(require_admin),
):
    """Query audit log. Admin-only."""
    results = []
    if not AUDIT_LOG.exists():
        return {"entries": [], "total": 0}
    
    entries = []
    with open(AUDIT_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if action and entry.get("action") != action:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    
    # Return last N entries (most recent)
    results = entries[-limit:]
    return {"entries": results, "total": len(entries)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("LISA_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)