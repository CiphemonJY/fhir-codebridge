#!/usr/bin/env python3
"""Download and parse NLM RxNorm data via REST API (public domain)."""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    parser = argparse.ArgumentParser(description="Download NLM RxNorm")
    parser.add_argument("--output", default="data/terminology_parsed/rxnorm.json")
    args = parser.parse_args()

    try:
        from scripts.build_terminology_data import download_rxnorm
        entries = download_rxnorm()
        with open(args.output, "w") as f:
            json.dump(entries, f, indent=2)
        print(f"Downloaded {len(entries)} RxNorm entries to {args.output}")
    except ImportError:
        print("ERROR: build_terminology_data.py not found. Run from repo root.")
        sys.exit(1)

if __name__ == "__main__":
    main()
