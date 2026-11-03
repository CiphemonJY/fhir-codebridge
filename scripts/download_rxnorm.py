#!/usr/bin/env python3
"""Download and parse NLM RxNorm data via the RxNav REST API (public domain).

Uses the public getAllConceptsByTTY endpoint, which needs no API key:
    https://rxnav.nlm.nih.gov/REST/allconcepts.json?tty=IN+PIN+BN+SCDC+SBD

Entries already in the output file that did not come from the API (for
example the ones loaded from the project TSV) are kept, unless the API now
returns the same RxCUI.

Usage:
    python3 scripts/download_rxnorm.py [--output data/terminology_parsed/rxnorm.json]
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

RXNAV_ALLCONCEPTS = "https://rxnav.nlm.nih.gov/REST/allconcepts.json"
# The term types the shipped rxnorm.json was built from.
DEFAULT_TTYS = ["IN", "PIN", "BN", "SCDC", "SBD"]
API_SOURCE = "NLM RxNorm REST API (public domain)"
USER_AGENT = "fhir-codebridge-terminology-updater/1.0 (+https://github.com/CiphemonJY/fhir-codebridge)"

# The shipped file has ~47K API concepts. Refuse to write a far smaller file,
# so a partial or empty API response can never wipe the shipped data.
DEFAULT_MIN_CONCEPTS = 40000


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.load(resp)


def download_rxnorm(ttys=None, fetch=None):
    """Return RxNorm concepts for the given term types as codebridge entries."""
    ttys = ttys or DEFAULT_TTYS
    url = f"{RXNAV_ALLCONCEPTS}?tty={'+'.join(urllib.parse.quote(t) for t in ttys)}"
    print(f"Downloading RxNorm concepts from {url}")
    data = (fetch or fetch_json)(url)
    concepts = ((data or {}).get("minConceptGroup") or {}).get("minConcept") or []
    entries = []
    seen = set()
    for c in concepts:
        code, name, tty = c.get("rxcui"), c.get("name"), c.get("tty")
        if not code or not name or code in seen:
            continue
        seen.add(code)
        entries.append({"system": "RXNORM", "code": str(code), "display": name,
                        "tty": tty, "source": API_SOURCE})
    entries.sort(key=lambda e: e["display"].lower())
    return entries


def merge_with_existing(api_entries, existing):
    """Keep non-API entries from the existing file whose code the API did not return."""
    api_codes = {e["code"] for e in api_entries}
    kept = [e for e in existing
            if e.get("source") != API_SOURCE and e.get("code") not in api_codes]
    return api_entries + kept, len(kept)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download NLM RxNorm")
    parser.add_argument("--output", default="data/terminology_parsed/rxnorm.json")
    parser.add_argument("--tty", nargs="+", default=DEFAULT_TTYS,
                        help="RxNorm term types to download")
    parser.add_argument("--min-concepts", type=int, default=DEFAULT_MIN_CONCEPTS,
                        help="Fail instead of writing if fewer API concepts are returned")
    args = parser.parse_args(argv)

    try:
        entries = download_rxnorm(args.tty)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"ERROR: RxNav request failed: {e}")
        return 1

    print(f"  Received {len(entries)} RxNorm concepts")
    if len(entries) < args.min_concepts:
        print(f"ERROR: expected at least {args.min_concepts} concepts; not writing {args.output}")
        return 1

    existing = []
    if os.path.exists(args.output):
        with open(args.output) as f:
            existing = json.load(f)
    merged, kept = merge_with_existing(entries, existing)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(merged, f, indent=2)
    print(f"Saved {len(merged)} RxNorm entries to {args.output} "
          f"({len(entries)} from the API, {kept} kept from the existing file)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
