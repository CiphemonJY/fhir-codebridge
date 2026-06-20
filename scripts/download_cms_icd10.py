#!/usr/bin/env python3
"""Download and parse CMS ICD-10-CM codes from cms.gov (public domain).

CMS ICD-10-CM code descriptions are public domain and freely redistributable.
This script downloads the CMS ICD-10-CM codes and converts them to JSON format.

Usage:
    python3 scripts/download_cms_icd10.py [--output data/terminology_parsed/icd10cm_full.json]
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import zipfile
import tempfile

CMS_URL = "https://www.cms.gov/files/zip/2027-icd-10-cm-code-tables-zip.zip"

def download_cms_icd10():
    """Download CMS ICD-10-CM code tables and convert to JSON."""
    print(f"Downloading CMS ICD-10-CM from {CMS_URL}...")
    
    entries = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "icd10.zip")
        urllib.request.urlretrieve(CMS_URL, zip_path)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Find the tabular or description file
            for name in zf.namelist():
                print(f"  Found: {name}")
            
            # Look for the code description file
            desc_file = None
            for name in zf.namelist():
                if name.endswith('.txt') and ('tabular' in name.lower() or 'description' in name.lower() or 'order' in name.lower()):
                    desc_file = name
                    break
            
            if not desc_file:
                # Try any .txt file
                for name in zf.namelist():
                    if name.endswith('.txt'):
                        desc_file = name
                        break
            
            if not desc_file:
                print("ERROR: No code file found in ZIP")
                sys.exit(1)
            
            print(f"  Parsing: {desc_file}")
            with zf.open(desc_file) as f:
                for line in f:
                    line = line.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                    # CMS format: code\tdescription
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        code = parts[0].strip()
                        display = parts[1].strip()
                        if code and re.match(r'^[A-Z]\d', code):
                            entries.append({
                                "code": code,
                                "system": "ICD-10-CM",
                                "display": display,
                                "source": "CMS 2027 ICD-10-CM (public domain)"
                            })
    
    print(f"  Parsed {len(entries)} ICD-10-CM codes")
    return entries

def main():
    parser = argparse.ArgumentParser(description="Download CMS ICD-10-CM codes")
    parser.add_argument("--output", default="data/terminology_parsed/icd10cm_full.json",
                       help="Output JSON file path")
    args = parser.parse_args()
    
    entries = download_cms_icd10()
    
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(entries, f, indent=2)
    
    print(f"Saved {len(entries)} ICD-10-CM codes to {args.output}")

if __name__ == "__main__":
    main()
