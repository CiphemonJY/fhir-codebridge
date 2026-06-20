#!/usr/bin/env python3
"""
Check documentation for potential unverified claims.

Flags:
  - Compliance certification claims ("HIPAA compliant", "certified", "FDA cleared")
  - Competitor comparison tables in README
  - Performance numbers without "measured" or "estimated" qualifier
  - Hardcoded term counts (should match stats() output)
  - Deployment time claims ("in X minutes", "under X minutes")
  - "verified" labels without source citation

Usage:
    python3 scripts/check_claims.py [--files FILE...] [--strict]
    
Exit codes:
    0 = no issues found
    1 = potential issues found (warnings)
    2 = definitive issues found (errors, --strict mode)
"""
import argparse
import os
import re
import sys

# Files that are allowed to discuss claims (the guidelines themselves)
SKIP_FILES = {'docs/CLAIM_VERIFICATION.md', './docs/CLAIM_VERIFICATION.md'}

# Patterns that indicate potential unverified claims
ERROR_PATTERNS = [
    # Compliance certification claims (not in the guidelines file)
    (r'\b(?:HIPAA|GDPR|SOC\s*2|FDA|ONC)\b.*\bcompliant\b',
     'ERROR: Compliance certification claim. Use "implements [requirement]" not "compliant".'),
    # Competitor comparison tables
    (r'\|.*(?:3M|Solventum|HAPI|cTAKES).*\|.*(?:✅|❌|—).*\|',
     'ERROR: Competitor comparison table detected. Remove per CLAIM_VERIFICATION.md.'),
]

WARNING_PATTERNS = [
    # Performance numbers without qualifier (check whole line for ESTIMATED/measured)
    (r'~\d+\s*(?:seconds|ms|MB|GB)\b',
     'WARN: Performance number without "measured" or "ESTIMATED" qualifier.',
     'line_has_estimated'),
    # Deployment time claims
    (r'(?:in|under|less than)\s*\d+\s*minutes?(?!.*(?:measured|estimated))',
     'WARN: Deployment time claim. Remove specific time estimates.'),
    # "verified" without source citation nearby
    (r'\bverified\b(?!.*(?:source|NLM|CMS|AHRQ|KFF|UMLS|official|manually|computed|not|date|level|confidence|badge|NLM-verified))',
     'WARN: "verified" used without citing a source. Add citation or use "computed".'),
    # Hardcoded term counts (should match stats())
    (r'\b\d{5,6}\s*(?:terms|entries|codes|mappings)\b',
     'WARN: Hardcoded term count. Verify against GET /stats output.'),
    # "safe for" claims
    (r'\bsafe for\s+(?:automated|clinical|production)\b',
     'WARN: "safe for" implies a guarantee. Use "appropriate for" instead.'),
]

def check_file(filepath):
    issues = []
    if filepath in SKIP_FILES or filepath.lstrip("./") in SKIP_FILES or any(filepath.endswith(s) for s in SKIP_FILES):
        return issues
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for lineno, line in enumerate(f, 1):
                for pattern, message in ERROR_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(('ERROR', lineno, message, line.strip()))
                for entry in WARNING_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        issues.append(('WARN', lineno, message, line.strip()))
    except (UnicodeDecodeError, IsADirectoryError):
        pass
    return issues

def main():
    parser = argparse.ArgumentParser(description="Check docs for unverified claims")
    parser.add_argument('--files', nargs='*', default=None,
                       help='Files to check (default: all .md files)')
    parser.add_argument('--strict', action='store_true',
                       help='Treat warnings as errors')
    args = parser.parse_args()
    
    if args.files:
        files = args.files
    else:
        # Find all .md files
        files = []
        for root, dirs, filenames in os.walk('.'):
            if '.git' in root:
                continue
            for fn in filenames:
                if fn.endswith('.md'):
                    files.append(os.path.join(root, fn))
    
    total_errors = 0
    total_warnings = 0
    
    for filepath in sorted(files):
        issues = check_file(filepath)
        if issues:
            print(f"\n{filepath}:")
            for level, lineno, message, line in issues:
                print(f"  {level} L{lineno}: {message}")
                print(f"    > {line}")
                if level == 'ERROR':
                    total_errors += 1
                else:
                    total_warnings += 1
    
    print(f"\n{'='*60}")
    print(f"Total: {total_errors} errors, {total_warnings} warnings")
    
    if total_errors > 0:
        sys.exit(2)
    if args.strict and total_warnings > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
