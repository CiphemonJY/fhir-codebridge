#!/usr/bin/env python3
"""
Build terminology data for fhir-codebridge.

Converts verified source data (TSV, Synthea crosswalk) into JSON format.
Does NOT generate or hallucinate terminology codes — only converts real data.

For full terminology coverage, hospitals must provide:
- UMLS Metathesaurus (MRCONSO.RRF) — provides SNOMED-CT, ICD-10-CM, LOINC, RxNorm
- Or individual system downloads (see data/terminology_parsed/README.md)

Usage:
  python3 scripts/build_terminology_data.py                    # Build from shipped sources
  python3 scripts/build_terminology_data.py --umls MRCONSO.RRF  # Add UMLS data
  python3 scripts/build_terminology_data.py --icd10cm file.xml  # Add ICD-10-CM
  python3 scripts/build_terminology_data.py --loinc file.zip    # Add LOINC
  python3 scripts/build_terminology_data.py --rxnorm file.zip   # Add RxNorm
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DATA_DIR = ROOT_DIR / "data"
PARSED_DIR = DATA_DIR / "terminology_parsed"
RAW_DIR = DATA_DIR / "terminology_raw"

PARSED_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)


def convert_crosswalk():
    """Convert crosswalk_v3.json from dict format to list format."""
    src = DATA_DIR / "synthea" / "crosswalk_v3.json"
    if not src.exists():
        print("  SKIP: synthea/crosswalk_v3.json not found")
        return 0
    
    with open(src) as f:
        cw_dict = json.load(f)
    
    cw_list = []
    for source_key, data in cw_dict.items():
        cw_list.append({
            'source': source_key,
            'target_code': data['db_523_code'],
            'target_system': data['db_523_system'],
            'target_display': data['db_523_display'],
            'similarity': data['similarity'],
            'same_system': data['same_system_match']
        })
    
    with open(PARSED_DIR / "crosswalk_v3.json", 'w') as f:
        json.dump(cw_list, f, indent=2)
    return len(cw_list)


def convert_tsv(tsv_path, json_path, system_override=None):
    """Convert a TSV file (code, system, display) to JSON."""
    entries = []
    with open(tsv_path) as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 3:
                code, system, display = parts[0], parts[1], parts[2]
                if system_override:
                    system = system_override
                entries.append({'code': code, 'system': system, 'display': display})
    with open(json_path, 'w') as f:
        json.dump(entries, f, indent=2)
    return len(entries)


def load_umls(mrconso_path):
    """
    Load UMLS Metathesaurus MRCONSO.RRF file.
    Provides SNOMED-CT, ICD-10-CM, LOINC, RxNorm, CPT, and 200+ vocabularies.
    """
    sys_map = {
        'ICD10CM': 'ICD-10-CM',
        'SNOMEDCT_US': 'SNOMED-CT',
        'LNC': 'LOINC',
        'RXNORM': 'RXNORM',
        'CDT': 'CDT',
        'CPT': 'CPT',
        'CVX': 'CVX',
    }
    
    by_system = {}
    count = 0
    
    with open(mrconso_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            parts = line.strip().split('|')
            if len(parts) < 15:
                continue
            lat = parts[1].strip()
            sab = parts[11].strip()
            tty = parts[12].strip()
            code = parts[13].strip()
            name = parts[14].strip()
            suppress = parts[16].strip() if len(parts) > 16 else ''
            is_pref = parts[6].strip() if len(parts) > 6 else ''
            
            # Only English, preferred terms, non-suppressed
            if lat != 'ENG' or suppress == 'O' or is_pref != 'Y':
                continue
            
            sys_name = sys_map.get(sab)
            if not sys_name:
                continue  # Skip vocabularies we don't handle
            
            if sys_name not in by_system:
                by_system[sys_name] = []
            
            by_system[sys_name].append({
                'code': code,
                'system': sys_name,
                'display': name
            })
            count += 1
    
    # Write each system to its own file
    for sys_name, entries in by_system.items():
        filename = {
            'ICD-10-CM': 'icd10cm.json',
            'SNOMED-CT': 'snomed_ct.json',
            'LOINC': 'loinc.json',
            'RXNORM': 'rxnorm_full.json',
            'CDT': 'cdt_full.json',
            'CPT': 'cpt.json',
            'CVX': 'cvx.json',
        }.get(sys_name, f'{sys_name.lower().replace("-", "_")}.json')
        
        # Dedup by code
        seen = set()
        unique = []
        for e in entries:
            if e['code'] not in seen:
                seen.add(e['code'])
                unique.append(e)
        
        with open(PARSED_DIR / filename, 'w') as f:
            json.dump(unique, f, indent=2)
        print(f"  {filename}: {len(unique):,} entries")
    
    return count


def main():
    parser = argparse.ArgumentParser(
        description='Build terminology data for fhir-codebridge'
    )
    parser.add_argument('--umls', metavar='MRCONSO.RRF',
                        help='Load UMLS Metathesaurus file (provides all systems)')
    parser.add_argument('--icd10cm', metavar='FILE',
                        help='Load ICD-10-CM from CMS download')
    parser.add_argument('--loinc', metavar='FILE',
                        help='Load LOINC from loinc.org download')
    parser.add_argument('--rxnorm', metavar='FILE',
                        help='Load RxNorm from NLM download')
    args = parser.parse_args()
    
    print("=== Building Terminology Data ===\n")
    
    # 1. Always convert shipped source data
    print("1. Converting shipped source data (verified)...")
    
    # Crosswalk
    count = convert_crosswalk()
    print(f"  crosswalk_v3.json: {count:,} mappings")
    
    # db_523 ontology
    ont_path = DATA_DIR / "combined_ontology.tsv"
    if ont_path.exists():
        count = convert_tsv(ont_path, PARSED_DIR / "db523_ontology.json")
        print(f"  db523_ontology.json: {count:,} entries")
    
    # LOINC core
    loinc_path = DATA_DIR / "loinc_core.tsv"
    if loinc_path.exists():
        count = convert_tsv(loinc_path, PARSED_DIR / "loinc_core.json", "LOINC")
        print(f"  loinc_core.json: {count:,} entries")
    
    # RxNorm core (from snomed_core.tsv — actually RxNorm data despite filename)
    rxnorm_path = DATA_DIR / "snomed_core.tsv"
    if rxnorm_path.exists():
        count = convert_tsv(rxnorm_path, PARSED_DIR / "rxnorm.json", "RXNORM")
        print(f"  rxnorm.json: {count:,} entries")
    
    # CDT codes
    cdt_path = DATA_DIR / "synthea" / "target_cdt_codes.json"
    if cdt_path.exists():
        with open(cdt_path) as f:
            cdt = json.load(f)
        with open(PARSED_DIR / "cdt.json", 'w') as f:
            json.dump(cdt, f, indent=2)
        print(f"  cdt.json: {len(cdt):,} entries")
    
    # 2. Load external data if provided
    if args.umls:
        print(f"\n2. Loading UMLS from {args.umls}...")
        count = load_umls(args.umls)
        print(f"  Total UMLS entries loaded: {count:,}")
    
    if args.icd10cm:
        print(f"\n3. Loading ICD-10-CM from {args.icd10cm}...")
        print("  (Not yet implemented — use --umls for ICD-10-CM)")
    
    if args.loinc:
        print(f"\n4. Loading LOINC from {args.loinc}...")
        print("  (Not yet implemented — use --umls for LOINC)")
    
    if args.rxnorm:
        print(f"\n5. Loading RxNorm from {args.rxnorm}...")
        print("  (Not yet implemented — use --umls for RxNorm)")
    
    # 3. Summary
    print("\n=== Summary ===")
    total = 0
    for fname in sorted(os.listdir(PARSED_DIR)):
        if fname.endswith('.json'):
            with open(PARSED_DIR / fname) as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else len(data)
            total += count
            print(f"  {fname:30} {count:>7,} entries")
    
    print(f"\n  Total: {total:,} entries")
    
    if not args.umls:
        print("\n  ⚠️  Shipped data only. For full coverage, load UMLS:")
        print("     python3 scripts/build_terminology_data.py --umls /path/to/MRCONSO.RRF")
        print("     (Adds 600K+ terms: SNOMED-CT, ICD-10-CM, LOINC, RxNorm)")
    
    print("\nDone. Test with:")
    print("  python3 -c \"import sys; sys.path.insert(0, 'scripts'); from rag.rag_lookup import RAGLookup; r = RAGLookup(); print(r.stats())\"")


if __name__ == '__main__':
    main()