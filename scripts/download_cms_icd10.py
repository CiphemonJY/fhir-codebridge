#!/usr/bin/env python3
"""Download and parse CMS ICD-10-CM codes from cms.gov (public domain)."""
import argparse
import json
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    parser = argparse.ArgumentParser(description="Download CMS ICD-10-CM")
    parser.add_argument("--output", default="data/terminology_parsed/icd10cm_full.json")
    args = parser.parse_args()

    try:
        from scripts.build_terminology_data import download_cms_icd10
        entries = download_cms_icd10()
        with open(args.output, "w") as f:
            json.dump(entries, f, indent=2)
        print(f"Downloaded {len(entries)} ICD-10-CM codes to {args.output}")
    except ImportError:
        print("ERROR: build_terminology_data.py not found. Run from repo root.")
        sys.exit(1)

if __name__ == "__main__":
    main()
