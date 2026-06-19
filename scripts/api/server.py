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
  - API key auth via CODEBRIDGE_API_KEYS env var (comma-separated)
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
from fastapi import FastAPI, HTTPException, Query, Request, Security, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from typing import Optional
import csv
import io

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
API_KEYS_ENV = _read_secret("CODEBRIDGE_API_KEYS")
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
# Safety: must explicitly set CODEBRIDGE_AUTH_DISABLED=1 to run without auth
AUTH_EXPLICITLY_DISABLED = os.environ.get("CODEBRIDGE_AUTH_DISABLED", "").strip() in ("1", "true", "yes")
AUTH_ENABLED = bool(API_KEYS) or not AUTH_EXPLICITLY_DISABLED
if AUTH_EXPLICITLY_DISABLED and not API_KEYS:
    print("WARNING: CODEBRIDGE_AUTH_DISABLED=1 — API is running in open mode (no authentication). "
          "Do NOT use in production.")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Audit log path
AUDIT_LOG = Path(os.environ.get("CODEBRIDGE_AUDIT_LOG", "data/audit.log"))
AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

# --- Init ---
app = FastAPI(
    title="fhir-codebridge FHIR Terminology Service",
    description="Open source on-prem terminology mapper. Bring your UMLS API key for full coverage.",
    version="0.2.0",
)

# CORS: configurable via env var, defaults to restrictive (no wildcard + credentials)
CORS_ORIGINS = os.environ.get("CODEBRIDGE_CORS_ORIGINS", "").strip()
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in CORS_ORIGINS.split(",")],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )
# No CORS middleware if CODEBRIDGE_CORS_ORIGINS not set = same-origin only (most secure)

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
        return "admin"  # Only reached if CODEBRIDGE_AUTH_DISABLED=1 is explicitly set
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


# --- Bulk CSV Processing ---

@app.post("/bulk")
async def bulk_lookup(
    request: Request,
    file: UploadFile = File(...),
    source_system: str = Form(...),
    target_system: str = Form(None),
    role: str = Depends(get_api_key),
):
    """
    Upload a CSV with a 'code' column. Maps all codes and returns results as CSV.
    Designed for non-technical users — hospital analysts with Excel files.
    """
    content = await file.read()
    text = content.decode("utf-8-sig")  # handle BOM from Excel
    
    # Parse CSV
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV file appears to be empty or malformed.")
    
    # Find the code column (case-insensitive)
    code_col = None
    for fn in reader.fieldnames:
        if fn.strip().lower() in ("code", "codes", "diagnosis_code", "dx_code", "icd10", "icd-10"):
            code_col = fn
            break
    if not code_col:
        # If only one column, use it
        if len(reader.fieldnames) == 1:
            code_col = reader.fieldnames[0]
        else:
            raise HTTPException(
                400,
                f"Could not find a code column. Expected one of: code, codes, diagnosis_code, dx_code. "
                f"Found columns: {', '.join(reader.fieldnames)}"
            )
    
    src_sys = normalize_system(source_system)
    tgt_sys = normalize_system(target_system) if target_system else None
    
    results = []
    matched = 0
    not_found = 0
    errors = 0
    
    for row in reader:
        code = (row.get(code_col) or "").strip()
        if not code:
            continue
        try:
            result = rag.map_with_confidence(
                code=code,
                system=src_sys,
                target_system=tgt_sys,
            )
            if result["found"]:
                matched += 1
                source_display = result.get("source", {}).get("display", "")
                targets = result.get("targets", [])
                if targets:
                    best = targets[0]
                    results.append({
                        "original_code": code,
                        "original_description": source_display,
                        "mapped_code": best["code"],
                        "mapped_description": best["display"],
                        "mapped_system": best["system"],
                        "confidence": f"{best['confidence']:.2f}",
                        "confidence_label": _confidence_label(best["confidence"]),
                        "action": result["action"],
                    })
                else:
                    results.append({
                        "original_code": code,
                        "original_description": source_display,
                        "mapped_code": "",
                        "mapped_description": "",
                        "mapped_system": "",
                        "confidence": "",
                        "confidence_label": "",
                        "action": "no_target",
                    })
            else:
                not_found += 1
                results.append({
                    "original_code": code,
                    "original_description": "",
                    "mapped_code": "",
                    "mapped_description": "",
                    "mapped_system": "",
                    "confidence": "",
                    "confidence_label": "",
                    "action": "not_found",
                })
        except Exception as e:
            errors += 1
            results.append({
                "original_code": code,
                "original_description": f"ERROR: {e}",
                "mapped_code": "",
                "mapped_description": "",
                "mapped_system": "",
                "confidence": "",
                "confidence_label": "",
                "action": "error",
            })
    
    audit_log(request, "bulk", {
        "filename": file.filename,
        "source_system": src_sys,
        "target_system": tgt_sys,
        "total": len(results),
        "matched": matched,
        "not_found": not_found,
        "errors": errors,
    })
    
    # Return results as CSV for easy Excel open
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "original_code", "original_description",
        "mapped_code", "mapped_description", "mapped_system",
        "confidence", "confidence_label", "action",
    ])
    writer.writeheader()
    writer.writerows(results)
    
    summary = f"# Summary: {matched} matched, {not_found} not found, {errors} errors out of {len(results)} total\n"
    
    return StreamingResponse(
        io.StringIO(summary + output.getvalue()),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=codebridge_results_{int(time.time())}.csv"
        },
    )


def _confidence_label(conf: float) -> str:
    """Convert 0.95 to 'High', 0.80 to 'Medium', etc."""
    if conf >= 0.95:
        return "High"
    elif conf >= 0.80:
        return "Medium"
    elif conf >= 0.60:
        return "Low"
    else:
        return "Very Low"


# --- Web UI (single HTML file, no build step, no extra deps) ---

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Serve the non-technical user web interface."""
    return WEB_UI_HTML


WEB_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>fhir-codebridge — FHIR Terminology Mapper</title>
<style>
:root {
  --bg: #f0f4f8; --card: #fff; --border: #d1d9e0; --text: #1a2a3a;
  --primary: #2563eb; --primary-hover: #1d4ed8; --green: #16a34a;
  --yellow: #ca8a04; --red: #dc2626; --muted: #6b7280;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.6; }
.container { max-width: 960px; margin: 0 auto; padding: 1rem; }
header { background: var(--card); border-bottom: 2px solid var(--border); padding: 1rem 0; }
header h1 { font-size: 1.5rem; } header p { color: var(--muted); font-size: 0.9rem; }
nav { display: flex; gap: 0.5rem; margin-top: 1rem; }
nav button { padding: 0.5rem 1rem; border: 1px solid var(--border); background: var(--card);
  border-radius: 6px; cursor: pointer; font-size: 0.9rem; transition: all 0.15s; }
nav button.active { background: var(--primary); color: #fff; border-color: var(--primary); }
nav button:hover:not(.active) { background: #e8eef5; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 1.5rem; margin-top: 1rem; }
.form-row { display: flex; gap: 1rem; flex-wrap: wrap; align-items: end; }
.form-group { flex: 1; min-width: 180px; }
.form-group label { display: block; font-size: 0.85rem; font-weight: 600; margin-bottom: 0.3rem; }
input[type="text"], select { width: 100%; padding: 0.6rem; border: 1px solid var(--border);
  border-radius: 6px; font-size: 0.95rem; }
.btn { padding: 0.6rem 1.5rem; border: none; border-radius: 6px; font-size: 0.95rem;
  cursor: pointer; font-weight: 600; transition: all 0.15s; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover { background: var(--primary-hover); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.result-card { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px;
  padding: 1rem; margin-top: 1rem; }
.badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
.badge-green { background: #dcfce7; color: var(--green); }
.badge-yellow { background: #fef9c3; color: var(--yellow); }
.badge-red { background: #fee2e2; color: var(--red); }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 1rem; }
.stat-box { background: #f8fafc; border: 1px solid var(--border); border-radius: 8px; padding: 1rem; text-align: center; }
.stat-box .num { font-size: 1.8rem; font-weight: 700; color: var(--primary); }
.stat-box .label { font-size: 0.8rem; color: var(--muted); margin-top: 0.2rem; }
.drop-zone { border: 2px dashed var(--border); border-radius: 8px; padding: 2rem;
  text-align: center; cursor: pointer; transition: all 0.15s; }
.drop-zone:hover, .drop-zone.dragover { border-color: var(--primary); background: #eff6ff; }
.drop-zone p { color: var(--muted); margin-top: 0.5rem; }
table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
th { background: #f8fafc; font-weight: 600; }
.spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--border);
  border-top-color: var(--primary); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.hidden { display: none; }
.error-msg { background: #fee2e2; color: var(--red); padding: 0.75rem 1rem; border-radius: 6px; margin-top: 1rem; }
.success-msg { background: #dcfce7; color: var(--green); padding: 0.75rem 1rem; border-radius: 6px; margin-top: 1rem; }
footer { text-align: center; color: var(--muted); font-size: 0.8rem; margin-top: 2rem; padding: 1rem; }
</style>
</head>
<body>
<header>
  <div class="container">
    <h1>fhir-codebridge</h1>
    <p>FHIR Terminology Mapper — map clinical codes across ICD-10, SNOMED, LOINC, RxNorm & CDT</p>
    <nav>
      <button id="nav-dashboard" class="active" onclick="showTab('dashboard')">Dashboard</button>
      <button id="nav-lookup" onclick="showTab('lookup')">Single Lookup</button>
      <button id="nav-bulk" onclick="showTab('bulk')">Bulk Upload</button>
    </nav>
  </div>
</header>

<div class="container">

<!-- DASHBOARD -->
<div id="tab-dashboard">
  <div class="card">
    <h2>Service Status</h2>
    <div id="status-loading"><span class="spinner"></span> Checking service...</div>
    <div id="status-content" class="hidden">
      <div class="stat-grid" id="stat-grid"></div>
    </div>
  </div>
  <div class="card">
    <h2>Terminology Coverage</h2>
    <div id="systems-loading"><span class="spinner"></span> Loading...</div>
    <div id="systems-content" class="hidden">
      <table id="systems-table"><thead><tr><th>System</th><th>Codes Loaded</th><th>FHIR URI</th></tr></thead><tbody></tbody></table>
    </div>
  </div>
  <div class="card">
    <h2>Recent Activity</h2>
    <p style="color:var(--muted)">Recent lookup activity appears here when the audit log has entries.</p>
  </div>
</div>

<!-- SINGLE LOOKUP -->
<div id="tab-lookup" class="hidden">
  <div class="card">
    <h2>Map a Single Code</h2>
    <p style="color:var(--muted);margin-bottom:1rem">Look up a clinical code and optionally map it to another terminology system.</p>
    <div class="form-row">
      <div class="form-group">
        <label>Code</label>
        <input type="text" id="lookup-code" placeholder="e.g., E11.9">
      </div>
      <div class="form-group">
        <label>From System</label>
        <select id="lookup-source">
          <option value="">Auto-detect</option>
          <option value="ICD-10-CM">ICD-10-CM</option>
          <option value="SNOMED-CT">SNOMED-CT</option>
          <option value="LOINC">LOINC</option>
          <option value="RXNORM">RxNorm</option>
          <option value="CDT">CDT</option>
        </select>
      </div>
      <div class="form-group">
        <label>Map To (optional)</label>
        <select id="lookup-target">
          <option value="">No mapping</option>
          <option value="ICD-10-CM">ICD-10-CM</option>
          <option value="SNOMED-CT">SNOMED-CT</option>
          <option value="LOINC">LOINC</option>
          <option value="RXNORM">RxNorm</option>
          <option value="CDT">CDT</option>
        </select>
      </div>
      <div class="form-group" style="flex:0">
        <button class="btn btn-primary" id="lookup-btn" onclick="doLookup()">Map It</button>
      </div>
    </div>
    <div id="lookup-result"></div>
  </div>
</div>

<!-- BULK UPLOAD -->
<div id="tab-bulk" class="hidden">
  <div class="card">
    <h2>Bulk Code Mapping</h2>
    <p style="color:var(--muted);margin-bottom:1rem">Upload a CSV file with a column of codes. We'll map them all and give you a downloadable results file.</p>
    <div class="form-row">
      <div class="form-group">
        <label>Your Code System</label>
        <select id="bulk-source">
          <option value="ICD-10-CM">ICD-10-CM</option>
          <option value="SNOMED-CT">SNOMED-CT</option>
          <option value="LOINC">LOINC</option>
          <option value="RXNORM">RxNorm</option>
          <option value="CDT">CDT</option>
        </select>
      </div>
      <div class="form-group">
        <label>Map To</label>
        <select id="bulk-target">
          <option value="SNOMED-CT">SNOMED-CT</option>
          <option value="ICD-10-CM">ICD-10-CM</option>
          <option value="LOINC">LOINC</option>
          <option value="RXNORM">RxNorm</option>
          <option value="CDT">CDT</option>
        </select>
      </div>
    </div>
    <div class="drop-zone" id="drop-zone" onclick="document.getElementById('file-input').click()">
      <p><strong>Click to select a CSV file</strong> or drag and drop here</p>
      <p style="font-size:0.8rem">File should have a column with codes (e.g., "code", "diagnosis_code", "dx_code")</p>
      <input type="file" id="file-input" accept=".csv" style="display:none" onchange="handleFile(this.files[0])">
    </div>
    <div id="file-info" class="hidden" style="margin-top:1rem"></div>
    <div id="bulk-progress" class="hidden" style="margin-top:1rem"><span class="spinner"></span> Processing codes...</div>
    <div id="bulk-result" style="margin-top:1rem"></div>
  </div>
</div>

</div>
<footer>
  <p>fhir-codebridge v0.2.0 — <a href="https://github.com/CiphemonJY/fhir-codebridge">GitHub</a> — MIT License</p>
</footer>

<script>
const API = window.location.origin;
const apiKey = new URLSearchParams(window.location.search).get('key') || '';
function headers() { const h = {'Content-Type':'application/json'}; if(apiKey) h['X-API-Key']=apiKey; return h; }

function showTab(tab) {
  ['dashboard','lookup','bulk'].forEach(t => {
    document.getElementById('tab-'+t).classList.toggle('hidden', t !== tab);
    document.getElementById('nav-'+t).classList.toggle('active', t === tab);
  });
  if(tab === 'dashboard') loadDashboard();
}

async function loadDashboard() {
  try {
    const r = await fetch(API + '/health');
    const h = await r.json();
    document.getElementById('status-loading').classList.add('hidden');
    const grid = document.getElementById('status-content');
    grid.classList.remove('hidden');
    document.getElementById('stat-grid').innerHTML = `
      <div class="stat-box"><div class="num" style="color:${h.status==='ok'?'var(--green)':'var(--red)'}">${h.status === 'ok' ? 'Running' : 'Down'}</div><div class="label">Service Status</div></div>
      <div class="stat-box"><div class="num">${(h.terms_loaded||0).toLocaleString()}</div><div class="label">Terms Loaded</div></div>
      <div class="stat-box"><div class="num" style="color:${h.umls_enabled?'var(--green)':'var(--yellow)'}">${h.umls_enabled ? 'Yes' : 'No'}</div><div class="label">UMLS Full Load</div></div>
      <div class="stat-box"><div class="num">v${h.version}</div><div class="label">Version</div></div>
    `;
  } catch(e) {
    document.getElementById('status-loading').innerHTML = '<div class="error-msg">Could not reach service. Is it running?</div>';
  }
  try {
    const r = await fetch(API + '/systems', {headers: headers()});
    if(r.ok) {
      const s = await r.json();
      document.getElementById('systems-loading').classList.add('hidden');
      document.getElementById('systems-content').classList.remove('hidden');
      const tbody = document.querySelector('#systems-table tbody');
      tbody.innerHTML = s.systems.map(sys =>
        `<tr><td><strong>${sys.name}</strong></td><td>${sys.count.toLocaleString()}</td><td style="color:var(--muted);font-size:0.8rem">${sys.fhir_uri || '—'}</td></tr>`
      ).join('') + `<tr style="font-weight:600"><td>Total</td><td>${s.total_terms.toLocaleString()}</td><td></td></tr>`;
    } else {
      document.getElementById('systems-loading').innerHTML = '<p style="color:var(--muted)">Sign in with API key to see details.</p>';
    }
  } catch(e) {
    document.getElementById('systems-loading').innerHTML = '<p style="color:var(--muted)">Could not load systems.</p>';
  }
}

async function doLookup() {
  const code = document.getElementById('lookup-code').value.trim();
  if(!code) return;
  const source = document.getElementById('lookup-source').value;
  const target = document.getElementById('lookup-target').value;
  const btn = document.getElementById('lookup-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  const resultDiv = document.getElementById('lookup-result');
  resultDiv.innerHTML = '';
  try {
    const body = {code};
    if(source) body.system = source;
    if(target) body.target_system = target;
    const r = await fetch(API + '/lookup', {method:'POST', headers:headers(), body:JSON.stringify(body)});
    const data = await r.json();
    if(!r.ok) { resultDiv.innerHTML = `<div class="error-msg">${data.detail || 'Lookup failed'}</div>`; return; }
    if(!data.found) { resultDiv.innerHTML = `<div class="result-card"><p>Code <strong>${code}</strong> not found.</p></div>`; return; }
    let html = '<div class="result-card">';
    if(data.source) {
      html += `<p><strong>Source:</strong> ${data.source.code} — ${data.source.display} <span style="color:var(--muted)">(${data.source.system})</span></p>`;
    }
    if(data.targets && data.targets.length > 0) {
      html += '<table><thead><tr><th>Mapped Code</th><th>System</th><th>Description</th><th>Confidence</th></tr></thead><tbody>';
      data.targets.forEach(t => {
        const badge = t.confidence >= 0.95 ? 'badge-green' : t.confidence >= 0.8 ? 'badge-yellow' : 'badge-red';
        const label = t.confidence >= 0.95 ? 'High' : t.confidence >= 0.8 ? 'Medium' : 'Low';
        html += `<tr><td><strong>${t.code}</strong></td><td>${t.system}</td><td>${t.display}</td><td><span class="badge ${badge}">${label} (${(t.confidence*100).toFixed(0)}%)</span></td></tr>`;
      });
      html += '</tbody></table>';
    } else if(data.source) {
      html += '<p style="color:var(--muted)">No cross-system mapping available. Code found in source system only.</p>';
    }
    html += '</div>';
    resultDiv.innerHTML = html;
  } catch(e) {
    resultDiv.innerHTML = `<div class="error-msg">Error: ${e.message}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = 'Map It';
  }
}

document.getElementById('lookup-code').addEventListener('keypress', e => { if(e.key === 'Enter') doLookup(); });

const dropZone = document.getElementById('drop-zone');
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault(); dropZone.classList.remove('dragover');
  if(e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
});

function handleFile(file) {
  document.getElementById('file-info').classList.remove('hidden');
  document.getElementById('file-info').innerHTML = `<p>Selected: <strong>${file.name}</strong> (${(file.size/1024).toFixed(1)} KB)</p>`;
  document.getElementById('bulk-result').innerHTML = '';
}

async function doBulk() {
  const fileInput = document.getElementById('file-input');
  if(!fileInput.files[0]) { alert('Please select a CSV file first.'); return; }
  const source = document.getElementById('bulk-source').value;
  const target = document.getElementById('bulk-target').value;
  const progress = document.getElementById('bulk-progress');
  const result = document.getElementById('bulk-result');
  progress.classList.remove('hidden');
  result.innerHTML = '';
  try {
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('source_system', source);
    formData.append('target_system', target);
    const r = await fetch(API + '/bulk', {
      method: 'POST',
      headers: apiKey ? {'X-API-Key': apiKey} : {},
      body: formData,
    });
    if(!r.ok) {
      const err = await r.json().catch(() => ({detail: 'Upload failed'}));
      result.innerHTML = `<div class="error-msg">${err.detail}</div>`;
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `codebridge_results.csv`; a.click();
    URL.revokeObjectURL(url);
    result.innerHTML = '<div class="success-msg">Done! Your results file has been downloaded. Open it in Excel.</div>';
  } catch(e) {
    result.innerHTML = `<div class="error-msg">Error: ${e.message}</div>`;
  } finally {
    progress.classList.add('hidden');
  }
}

// Add Process button dynamically after file selection
const observer = new MutationObserver(() => {
  const info = document.getElementById('file-info');
  if(!info.classList.contains('hidden') && !document.getElementById('process-btn')) {
    const btn = document.createElement('button');
    btn.id = 'process-btn'; btn.className = 'btn btn-primary'; btn.textContent = 'Map Codes';
    btn.style.marginTop = '0.5rem'; btn.onclick = doBulk;
    info.appendChild(btn);
  }
});
observer.observe(document.getElementById('file-info'), {attributes: true});

// Init
loadDashboard();
</script>
</body>
</html>"""


# --- Metrics endpoint (Prometheus-compatible, text format) ---

@app.get("/metrics")
async def metrics():
    """Prometheus-compatible metrics endpoint. No auth required (read-only stats)."""
    stats = rag.stats()
    total = stats.get("total_terms", 0)
    systems = stats.get("by_system", {})
    umls_loaded = stats.get("umls_loaded", False)
    lines = [
        "# HELP codebridge_terms_loaded Total terminology terms loaded",
        "# TYPE codebridge_terms_loaded gauge",
        f"codebridge_terms_loaded {total}",
        "",
        "# HELP codebridge_systems_loaded Number of coding systems with data",
        "# TYPE codebridge_systems_loaded gauge",
        f"codebridge_systems_loaded {len(systems)}",
        "",
        "# HELP codebridge_up Service health (1=up, 0=down)",
        "# TYPE codebridge_up gauge",
        "codebridge_up 1",
        "",
    ]
    # Per-system term counts
    for sys_name, count in systems.items():
        safe = sys_name.replace("-", "_").replace(" ", "_")
        lines.append(f"codebridge_system_terms{{system=\"{sys_name}\"}} {count}")
    lines.append("")
    # UMLS status
    umls = 1 if umls_loaded else 0
    lines.append("# HELP codebridge_umls_enabled Whether UMLS full load is active")
    lines.append("# TYPE codebridge_umls_enabled gauge")
    lines.append(f"codebridge_umls_enabled {umls}")
    return StreamingResponse(io.StringIO("\n".join(lines)), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CODEBRIDGE_PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)