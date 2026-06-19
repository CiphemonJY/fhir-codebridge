#!/usr/bin/env python3
"""
UMLS UTS API Client
===================
Looks up concepts and cross-system mappings via the NLM UTS REST API.
Requires a UMLS API key (free registration at https://uts.nlm.nih.gov/uts/signup).

Set env var: LISA_UMLS_API_KEY=your-key-here

The API key is NEVER stored or logged. It's read from the environment
and used only for outbound UTS API calls.
"""

import os
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional


class UMLSClient:
    """Thin client for the UMLS UTS REST API with rate limiting + cache."""
    
    BASE = "https://uts-ws.nlm.nih.gov/rest"
    
    # ponytail: in-memory cache + rate limit, no external deps
    _cache: dict = {}  # cache_key → (timestamp, data)
    _CACHE_TTL = 3600  # 1 hour
    _last_request_ts: float = 0
    _MIN_INTERVAL = 0.2  # 200ms between requests = max 5 req/s (NLM limit is ~20/s)
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("LISA_UMLS_API_KEY")
        if not self.api_key:
            # ponytail: check Docker secret file
            file_path = os.environ.get("LISA_UMLS_API_KEY_FILE")
            if file_path and os.path.exists(file_path):
                with open(file_path) as f:
                    self.api_key = f.read().strip()
        if not self.api_key:
            raise ValueError(
                "No UMLS API key found. Set LISA_UMLS_API_KEY env var "
                "or pass api_key to UMLSClient(). "
                "Get a free key at https://uts.nlm.nih.gov/uts/signup"
            )
        self._ticket_granting_ticket = None
    
    def _rate_limit(self):
        """Enforce min interval between UTS API calls."""
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self._MIN_INTERVAL:
            time.sleep(self._MIN_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()
    
    def _cache_get(self, key: str):
        """Return cached result if fresh, else None."""
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self._CACHE_TTL:
                return data
        return None
    
    def _cache_put(self, key: str, data):
        """Store result in cache."""
        self._cache[key] = (time.time(), data)
        # ponytail: unbounded cache, switch to LRU if memory matters at scale
    
    def _get_tgt(self):
        """Get a ticket-granting ticket (TGT) for UTS authentication."""
        if self._ticket_granting_ticket:
            return self._ticket_granting_ticket
        
        data = urllib.parse.urlencode({
            "apikey": self.api_key,
        }).encode()
        
        req = urllib.request.Request(
            f"{self.BASE}/authentication",
            data=data,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                # TGT URL is in the Location header
                tgt_url = resp.headers.get("Location", "")
                if tgt_url:
                    self._ticket_granting_ticket = tgt_url
                    return tgt_url
        except urllib.error.URLError as e:
            raise RuntimeError(f"UMLS authentication failed: {e}")
        
        return None
    
    def _get_service_ticket(self, tgt_url: str, service: str) -> str:
        """Get a single-use service ticket from the TGT."""
        data = urllib.parse.urlencode({"service": service}).encode()
        req = urllib.request.Request(tgt_url, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode().strip()
    
    def _get(self, path: str, params: dict) -> dict:
        """Make an authenticated GET request to the UTS API (with rate limit + cache)."""
        cache_key = f"{path}?{urllib.parse.urlencode(sorted(params.items()))}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        
        self._rate_limit()
        tgt = self._get_tgt()
        service_ticket = self._get_service_ticket(tgt, f"{self.BASE}{path}")
        
        params["ticket"] = service_ticket
        query = urllib.parse.urlencode(params)
        url = f"{self.BASE}{path}?{query}"
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            self._cache_put(cache_key, data)
            return data
    
    def get_concept(self, cui: str) -> Optional[dict]:
        """Get concept info by CUI."""
        try:
            data = self._get(f"/content/CUI/{cui}", {})
            return data.get("result")
        except (urllib.error.URLError, RuntimeError):
            return None
    
    def get_atoms(self, cui: str, sabs: Optional[list] = None) -> list:
        """
        Get all atoms (code/term pairs) for a concept.
        This is how we get cross-system mappings — one CUI has atoms in multiple SABs.
        """
        params = {"pageSize": 200}
        if sabs:
            params["sabs"] = ",".join(sabs)
        
        try:
            data = self._get(f"/content/CUI/{cui}/atoms", params)
            return data.get("result", [])
        except (urllib.error.URLError, RuntimeError):
            return []
    
    def search(self, term: str, sabs: Optional[list] = None) -> list:
        """Search for concepts by string. Returns list of CUIs with info."""
        params = {"string": term, "pageSize": 25}
        if sabs:
            params["sabs"] = ",".join(sabs)
        
        try:
            data = self._get("/search/current", params)
            return data.get("result", {}).get("results", [])
        except (urllib.error.URLError, RuntimeError):
            return []
    
    def get_code_mappings(self, system: str, code: str) -> list:
        """
        Given a code in any system, find all cross-system mappings.
        
        1. Look up the code to find its CUI
        2. Get all atoms for that CUI (atoms in other SABs = cross-system mappings)
        
        Returns list of {system, code, display} entries.
        """
        # Map our system names to UMLS SABs
        sab_map = {
            "ICD-10-CM": "ICD10CM",
            "SNOMED-CT": "SNOMEDCT_US",
            "LOINC": "LNC",
            "RXNORM": "RXNORM",
            "CDT": "CDT",
            "CPT": "CPT",
        }
        sab = sab_map.get(system, system)
        
        # Search by code within the source vocabulary
        results = self.search(f"{code}", sabs=[sab])
        
        if not results:
            return []
        
        # Get the first CUI (most relevant)
        cui = results[0].get("ui")
        if not cui or cui == "NONE":
            return []
        
        # Get all atoms for this CUI — these are the cross-system mappings
        target_sabs = list(sab_map.values())
        atoms = self.get_atoms(cui, sabs=target_sabs)
        
        # Map SABs back to our system names
        reverse_sab = {v: k for k, v in sab_map.items()}
        
        mappings = []
        seen = set()
        for atom in atoms:
            atom_sab = atom.get("rootSource", atom.get("termType", ""))
            atom_code = atom.get("code", atom.get("codeId", ""))
            atom_name = atom.get("name", "")
            
            our_system = reverse_sab.get(atom_sab, atom_sab)
            key = f"{our_system}|{atom_code}"
            
            if key not in seen and atom_code and atom_code != "NOCODE":
                seen.add(key)
                mappings.append({
                    "system": our_system,
                    "code": atom_code,
                    "display": atom_name,
                    "cui": cui,
                    "confidence": 1.0,  # UMLS-verified
                    "method": "umls_api_lookup",
                })
        
        return mappings


# CLI for testing
if __name__ == "__main__":
    import sys
    
    if not os.environ.get("LISA_UMLS_API_KEY"):
        print("Set LISA_UMLS_API_KEY env var first.")
        print("Get a free key at https://uts.nlm.nih.gov/uts/signup")
        sys.exit(1)
    
    client = UMLSClient()
    
    print("=== UMLS UTS API Test ===\n")
    
    # Test: search for a concept
    print("Search: 'type 2 diabetes'")
    results = client.search("type 2 diabetes")
    for r in results[:3]:
        print(f"  CUI: {r.get('ui')} — {r.get('name')}")
    
    # Test: cross-system mapping
    print("\nMappings for ICD-10-CM E11.9:")
    mappings = client.get_code_mappings("ICD-10-CM", "E11.9")
    for m in mappings:
        print(f"  {m['system']}|{m['code']} — {m['display']}")