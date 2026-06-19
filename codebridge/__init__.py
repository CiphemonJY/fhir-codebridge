#!/usr/bin/env python3
"""
fhir-codebridge client SDK.

Usage:
    from codebridge import CodeBridge

    cb = CodeBridge("http://localhost:8000", api_key="your-key")
    result = cb.lookup("E11.9", system="ICD-10-CM", target_system="SNOMED-CT")
    print(result)

    # Bulk mapping from a CSV file
    cb.bulk_map("codes.csv", source_system="ICD-10-CM", target_system="SNOMED-CT", output="results.csv")

    # Check service status
    stats = cb.stats()
    print(f"{stats['total_terms']} terms loaded")
"""

import json
import os
from typing import Optional, Dict, List, Any


class CodeBridge:
    """Client for the fhir-codebridge terminology mapping service."""

    def __init__(self, base_url: str = "http://localhost:8000", api_key: Optional[str] = None):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the fhir-codebridge service.
            api_key: API key for authentication. If None, reads from
                     CODEBRIDGE_API_KEY env var.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("CODEBRIDGE_API_KEY", "")
        self._session = None

    @property
    def session(self):
        """Lazy-init requests.Session with auth header."""
        if self._session is None:
            import requests
            self._session = requests.Session()
            if self.api_key:
                self._session.headers["X-API-Key"] = self.api_key
            self._session.headers["Content-Type"] = "application/json"
        return self._session

    def _get(self, path: str, **kwargs) -> Dict:
        """GET request with error handling."""
        resp = self.session.get(f"{self.base_url}{path}", **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_body: Dict = None, **kwargs) -> Dict:
        """POST request with error handling."""
        resp = self.session.post(f"{self.base_url}{path}", json=json_body, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> Dict:
        """Check service health. Returns status, version, terms loaded, etc."""
        return self._get("/health")

    def stats(self) -> Dict:
        """Get terminology coverage statistics."""
        return self._get("/stats")

    def systems(self) -> Dict:
        """List loaded coding systems and their term counts."""
        return self._get("/systems")

    def metrics(self) -> str:
        """Get Prometheus-format metrics (raw text)."""
        resp = self.session.get(f"{self.base_url}/metrics")
        resp.raise_for_status()
        return resp.text

    def lookup(
        self,
        code: str,
        system: Optional[str] = None,
        display: Optional[str] = None,
        target_system: Optional[str] = None,
        threshold: float = 0.6,
    ) -> Dict:
        """
        Look up a clinical code and optionally map it to another system.

        Args:
            code: The code to look up (e.g., "E11.9").
            system: Source coding system (e.g., "ICD-10-CM"). Auto-detected if omitted.
            display: Display text to search instead of code (fuzzy match).
            target_system: Map to this system (e.g., "SNOMED-CT").
            threshold: Minimum confidence for fuzzy matches (0.0-1.0).

        Returns:
            Dict with: found (bool), source (dict), targets (list), action,
            effective_confidence, requires_human_review.
        """
        body = {"code": code, "threshold": threshold}
        if system:
            body["system"] = system
        if display:
            body["display"] = display
        if target_system:
            body["target_system"] = target_system
        return self._post("/lookup", json_body=body)

    def translate(
        self,
        code: str,
        system: str,
        target_system: Optional[str] = None,
    ) -> Dict:
        """
        FHIR ConceptMap $translate operation.

        Args:
            code: Source code to translate.
            system: Source system URI or name (e.g., "ICD-10-CM").
            target_system: Target system URI or name.

        Returns:
            FHIR Parameters resource with translation results.
        """
        body = {"code": code, "system": system}
        if target_system:
            body["target_system"] = target_system
        return self._post("/$translate", json_body=body)

    def bulk_map(
        self,
        csv_path: str,
        source_system: str,
        target_system: str = None,
        output: str = None,
    ) -> str:
        """
        Bulk map codes from a CSV file. Returns results as CSV text.

        Args:
            csv_path: Path to CSV file with a code column.
            source_system: Source coding system (e.g., "ICD-10-CM").
            target_system: Target system to map to (e.g., "SNOMED-CT").
            output: If provided, save results to this file path.

        Returns:
            CSV text with columns: original_code, original_description,
            mapped_code, mapped_description, mapped_system, confidence,
            confidence_label, action.
        """
        import requests

        with open(csv_path, "rb") as f:
            files = {"file": (os.path.basename(csv_path), f, "text/csv")}
            data = {"source_system": source_system}
            if target_system:
                data["target_system"] = target_system

            headers = {}
            if self.api_key:
                headers["X-API-Key"] = self.api_key

            resp = requests.post(
                f"{self.base_url}/bulk",
                files=files,
                data=data,
                headers=headers,
            )
            resp.raise_for_status()
            csv_text = resp.text

        if output:
            with open(output, "w") as f:
                f.write(csv_text)

        return csv_text

    def audit(self, limit: int = 100, action: Optional[str] = None) -> Dict:
        """
        Query audit log (requires admin API key).

        Args:
            limit: Maximum entries to return.
            action: Filter by action type (e.g., "lookup", "translate", "bulk").

        Returns:
            Dict with total count and entries list.
        """
        params = {"limit": limit}
        if action:
            params["action"] = action
        return self._get("/audit", params=params)


def main():
    """CLI entry point for quick testing."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="fhir-codebridge client")
    parser.add_argument("--url", default="http://localhost:8000", help="Service URL")
    parser.add_argument("--key", default=None, help="API key")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("health", help="Check service health")
    sub.add_parser("stats", help="Show terminology stats")
    sub.add_parser("systems", help="List loaded systems")
    sub.add_parser("metrics", help="Show Prometheus metrics")

    p_lookup = sub.add_parser("lookup", help="Look up a code")
    p_lookup.add_argument("code", help="Code to look up")
    p_lookup.add_argument("--system", "-s", default=None, help="Source system")
    p_lookup.add_argument("--target", "-t", default=None, help="Target system")
    p_lookup.add_argument("--threshold", type=float, default=0.6, help="Min confidence")

    p_bulk = sub.add_parser("bulk", help="Bulk map codes from CSV")
    p_bulk.add_argument("file", help="CSV file path")
    p_bulk.add_argument("--source", "-s", required=True, help="Source system")
    p_bulk.add_argument("--target", "-t", default=None, help="Target system")
    p_bulk.add_argument("--output", "-o", default=None, help="Output CSV path")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cb = CodeBridge(args.url, api_key=args.key)

    if args.command == "health":
        print(json.dumps(cb.health(), indent=2))
    elif args.command == "stats":
        print(json.dumps(cb.stats(), indent=2))
    elif args.command == "systems":
        print(json.dumps(cb.systems(), indent=2))
    elif args.command == "metrics":
        print(cb.metrics())
    elif args.command == "lookup":
        result = cb.lookup(args.code, system=args.system, target_system=args.target, threshold=args.threshold)
        print(json.dumps(result, indent=2))
    elif args.command == "bulk":
        result = cb.bulk_map(args.file, source_system=args.source, target_system=args.target, output=args.output)
        if args.output:
            print(f"Results saved to {args.output}")
        else:
            print(result)


if __name__ == "__main__":
    main()