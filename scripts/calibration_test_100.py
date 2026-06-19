#!/usr/bin/env python3
"""
Calibration test for fhir-codebridge RAG lookup engine.

Tests three categories:
1. Auto-accept: Exact code lookups (should be 100% with any data)
2. Reject: Unknown codes (should correctly reject at < 70% confidence)
3. Fuzzy text: Display text matching (depends on loaded terminology)

Note: Fuzzy text matching results depend on loaded terminology.
With shipped data (920 terms), fuzzy matching is limited.
With UMLS loaded (600K+ terms), expect 95%+ on all categories.

Run: python3 scripts/calibration_test_100.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from rag.rag_lookup import RAGLookup

def main():
    rag = RAGLookup()
    stats = rag.stats()
    
    print("=" * 70)
    print("fhir-codebridge Calibration Test")
    print("=" * 70)
    
    print(f"\nLoaded terminology:")
    print(f"  Total terms: {stats['total_terms']:,}")
    print(f"  Crosswalk mappings: {stats['crosswalk_mappings']:,}")
    print(f"  UMLS loaded: {stats['umls_loaded']}")
    for sys_name, count in sorted(stats['by_system'].items(), key=lambda x: -x[1]):
        print(f"  {sys_name}: {count:,}")
    
    if stats['total_terms'] < 5000:
        print("\n  ⚠️  Limited data loaded — fuzzy text matching will be limited.")
        print("  For full calibration, load UMLS: see data/terminology_parsed/README.md")
    
    # === Test Cases ===
    test_cases = []
    
    # Category 1: Exact code lookups (should always work if code is in database)
    # Use codes we KNOW are in the shipped data
    if 'CDT' in stats['by_system']:
        # Load actual CDT codes from the database
        cdt_codes = [(k.split('|')[1], v['display']) for k, v in rag.by_code.items() if k.startswith('CDT|')]
        for i, (code, display) in enumerate(cdt_codes[:20]):
            test_cases.append({
                'category': 'auto_accept',
                'description': f'CDT exact lookup: {code}',
                'code': code,
                'system': 'CDT',
                'expected_action': 'auto_accept'
            })
    
    if 'RXNORM' in stats['by_system']:
        rxnorm_codes = [(k.split('|')[1], v['display']) for k, v in rag.by_code.items() if k.startswith('RXNORM|')]
        for i, (code, display) in enumerate(rxnorm_codes[:20]):
            test_cases.append({
                'category': 'auto_accept',
                'description': f'RxNorm exact lookup: {code}',
                'code': code,
                'system': 'RXNORM',
                'expected_action': 'auto_accept'
            })
    
    if 'LOINC' in stats['by_system']:
        loinc_codes = [(k.split('|')[1], v['display']) for k, v in rag.by_code.items() if k.startswith('LOINC|')]
        for i, (code, display) in enumerate(loinc_codes[:20]):
            test_cases.append({
                'category': 'auto_accept',
                'description': f'LOINC exact lookup: {code}',
                'code': code,
                'system': 'LOINC',
                'expected_action': 'auto_accept'
            })
    
    # Category 2: Reject cases (codes that don't exist in any system)
    reject_cases = [
        ('FAKE001', 'FAKE_SYSTEM'),
        ('NONEXIST999', 'CDT'),
        ('ZZZZZ', 'RXNORM'),
        ('0000000', 'LOINC'),
    ]
    for code, system in reject_cases:
        test_cases.append({
            'category': 'reject',
            'description': f'Unknown code: {system}|{code}',
            'code': code,
            'system': system,
            'expected_action': 'reject'
        })
    
    # Category 3: Fuzzy text matching (depends on loaded data)
    # These test the synonym map and abbreviation expansion
    fuzzy_cases = [
        ('htn', 'Essential hypertension (abbreviation)'),
        ('hypertension', 'Essential hypertension (full term)'),
        ('type 2 diabetes', 'Type 2 diabetes (synonym)'),
        ('t2dm', 'Type 2 diabetes (abbreviation)'),
        ('chest pain', 'Chest pain (symptom)'),
        ('back pain', 'Low back pain (symptom)'),
        ('migraine', 'Migraine (condition)'),
        ('anxiety', 'Anxiety (condition)'),
        ('depression', 'Depression (condition)'),
        ('fever', 'Fever (symptom)'),
    ]
    for text, desc in fuzzy_cases:
        test_cases.append({
            'category': 'fuzzy_text',
            'description': f'Fuzzy text: {desc}',
            'code': None,
            'display': text,
            'system': None,
            'expected_action': 'auto_accept'  # Synonym map should catch these
        })
    
    # === Run Tests ===
    print(f"\nRunning {len(test_cases)} test cases...\n")
    
    results = {
        'auto_accept': {'pass': 0, 'fail': 0, 'cases': []},
        'reject': {'pass': 0, 'fail': 0, 'cases': []},
        'fuzzy_text': {'pass': 0, 'fail': 0, 'cases': []},
    }
    
    for tc in test_cases:
        result = rag.map_with_confidence(
            code=tc.get('code'),
            system=tc.get('system'),
            display=tc.get('display'),
        )
        
        passed = result['action'] == tc['expected_action']
        status = '✅' if passed else '❌'
        
        results[tc['category']]['pass' if passed else 'fail'] += 1
        results[tc['category']]['cases'].append({
            'description': tc['description'],
            'expected': tc['expected_action'],
            'actual': result['action'],
            'confidence': result['effective_confidence'],
            'passed': passed,
        })
        
        if passed:
            print(f"  {status} {tc['description']}: {result['action']} @ {result['effective_confidence']:.1%}")
        else:
            print(f"  {status} {tc['description']}: expected {tc['expected_action']}, got {result['action']} @ {result['effective_confidence']:.1%}")
    
    # === Summary ===
    print("\n" + "=" * 70)
    print("CALIBRATION RESULTS")
    print("=" * 70)
    
    total_pass = sum(r['pass'] for r in results.values())
    total_fail = sum(r['fail'] for r in results.values())
    total = total_pass + total_fail
    
    for category, r in results.items():
        cat_total = r['pass'] + r['fail']
        if cat_total > 0:
            pct = r['pass'] / cat_total * 100
            print(f"  {category:15} {r['pass']}/{cat_total} ({pct:.1f}%)")
    
    print(f"\n  OVERALL         {total_pass}/{total} ({total_pass/total*100:.1f}%)")
    
    # Save results
    results_dir = Path(__file__).resolve().parent.parent / "results"
    results_dir.mkdir(exist_ok=True)
    
    output = {
        'timestamp': __import__('datetime').datetime.now().isoformat(),
        'data_loaded': stats,
        'total_tests': total,
        'total_pass': total_pass,
        'overall_pct': total_pass / total * 100,
        'categories': {
            cat: {
                'pass': r['pass'],
                'fail': r['fail'],
                'cases': r['cases'],
            }
            for cat, r in results.items()
        }
    }
    
    output_path = results_dir / "calibration_latest.json"
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {output_path}")
    
    # Exit code
    sys.exit(0 if total_pass == total else 1)


if __name__ == '__main__':
    main()