#!/usr/bin/env python3
"""Download and parse CMS ICD-10-CM codes from cms.gov (public domain).

CMS ICD-10-CM code descriptions are public domain and freely redistributable.
This script downloads the CMS "Code Descriptions in Tabular Order" ZIP for the
fiscal year in effect and converts the billable codes to JSON.

The release is picked by date: the ICD-10-CM fiscal year starts Oct 1, so a run
on 2026-11-02 uses FY2027. If CMS has posted an April 1 mid-year update for that
fiscal year, it is preferred over the Oct 1 release.

Usage:
    python3 scripts/download_cms_icd10.py [--output data/terminology_parsed/icd10cm_full.json]
    python3 scripts/download_cms_icd10.py --fiscal-year 2027
    python3 scripts/download_cms_icd10.py --url https://www.cms.gov/files/zip/<file>.zip
"""
import argparse
import datetime
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile

CMS_BASE = "https://www.cms.gov/files/zip/"
USER_AGENT = "fhir-codebridge-terminology-updater/1.0 (+https://github.com/CiphemonJY/fhir-codebridge)"

# A full ICD-10-CM release has ~74K billable codes. Refuse to write a file that
# is far smaller, so a changed file layout can never wipe the shipped data.
DEFAULT_MIN_CODES = 70000

# Codes file layout (CMS/NCHS): code without dots in columns 1-7, a blank,
# then the long description. No tab delimiter.
CODES_LINE = re.compile(r"^([A-Z][0-9A-Z][0-9A-Z]{1,5})\s+(\S.*)$")
# Order file layout: 5-digit order number, blank, code (7), blank,
# header flag (0 = header, 1 = billable), blank, short description (60),
# blank, long description.
ORDER_LINE = re.compile(r"^\d{5} ([A-Z][0-9A-Z][0-9A-Z ]{5}) ([01]) (.{60}) (\S.*)$")


def fiscal_year_for(date):
    """ICD-10-CM fiscal year in effect on a date (FY N runs Oct 1 N-1 to Sep 30 N)."""
    return date.year + 1 if date.month >= 10 else date.year


def candidate_releases(date, fiscal_year=None):
    """Return (label, url) pairs to try, newest first."""
    fy = fiscal_year or fiscal_year_for(date)
    candidates = []
    # The April 1 update for FY N takes effect in the spring of calendar year N.
    if fiscal_year is None and date >= datetime.date(fy, 4, 1):
        candidates.append((f"April {fy}", f"{CMS_BASE}april-1-{fy}-code-descriptions-tabular-order.zip"))
    candidates.append((f"{fy}", f"{CMS_BASE}{fy}-code-descriptions-tabular-order.zip"))
    return candidates


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def download_release(candidates):
    """Download the first candidate that exists. Returns (label, url, bytes)."""
    errors = []
    for label, url in candidates:
        print(f"Trying CMS ICD-10-CM {label}: {url}")
        try:
            data = fetch(url)
        except urllib.error.HTTPError as e:
            errors.append(f"{url} -> HTTP {e.code}")
            print(f"  Not available (HTTP {e.code})")
            continue
        if not zipfile.is_zipfile(io.BytesIO(data)):
            errors.append(f"{url} -> not a ZIP file")
            print("  Response was not a ZIP file")
            continue
        return label, url, data
    raise RuntimeError("No CMS ICD-10-CM release could be downloaded:\n  " + "\n  ".join(errors))


def pick_file(names, kind):
    """Pick the codes or order .txt file from the ZIP, skipping addenda."""
    for name in names:
        base = os.path.basename(name).lower()
        if not base.endswith(".txt") or "addenda" in base:
            continue
        if re.match(rf"icd10cm[-_]{kind}", base):
            return name
    return None


def parse_codes_file(lines):
    pairs = []
    for line in lines:
        m = CODES_LINE.match(line.rstrip("\r\n"))
        if m:
            pairs.append((m.group(1), m.group(2).strip()))
    return pairs


def parse_order_file(lines):
    pairs = []
    for line in lines:
        m = ORDER_LINE.match(line.rstrip("\r\n"))
        if m and m.group(2) == "1":  # billable codes only, like the codes file
            pairs.append((m.group(1).strip(), m.group(4).strip()))
    return pairs


def parse_zip(data):
    """Parse a CMS code-descriptions ZIP into (code, description) pairs."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        for name in names:
            print(f"  Found: {name}")
        codes_name = pick_file(names, "codes")
        if codes_name:
            print(f"  Parsing codes file: {codes_name}")
            text = zf.read(codes_name).decode("utf-8", errors="replace")
            return parse_codes_file(text.splitlines())
        order_name = pick_file(names, "order")
        if order_name:
            print(f"  Parsing order file: {order_name}")
            text = zf.read(order_name).decode("utf-8", errors="replace")
            return parse_order_file(text.splitlines())
    raise RuntimeError("No icd10cm codes or order file found in the CMS ZIP")


def to_entries(pairs, label):
    source = f"CMS {label} ICD-10-CM (public domain)"
    return [
        {"code": code, "system": "ICD-10-CM", "display": display, "source": source}
        for code, display in pairs
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download CMS ICD-10-CM codes")
    parser.add_argument("--output", default="data/terminology_parsed/icd10cm_full.json",
                        help="Output JSON file path")
    parser.add_argument("--fiscal-year", type=int,
                        help="Fiscal year to download (default: the one in effect today)")
    parser.add_argument("--url", default=os.environ.get("CMS_ICD10_URL"),
                        help="Exact CMS ZIP URL to use instead of the computed one")
    parser.add_argument("--min-codes", type=int, default=DEFAULT_MIN_CODES,
                        help="Fail instead of writing if fewer codes are parsed")
    args = parser.parse_args(argv)

    if args.url:
        candidates = [(str(args.fiscal_year or fiscal_year_for(datetime.date.today())), args.url)]
    else:
        candidates = candidate_releases(datetime.date.today(), args.fiscal_year)

    try:
        label, url, data = download_release(candidates)
        pairs = parse_zip(data)
    except (RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as e:
        print(f"ERROR: {e}")
        return 1

    print(f"  Parsed {len(pairs)} ICD-10-CM codes from {url}")
    if len(pairs) < args.min_codes:
        print(f"ERROR: expected at least {args.min_codes} codes; not writing {args.output}")
        return 1

    entries = to_entries(pairs, label)
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(entries, f, indent=2)
    print(f"Saved {len(entries)} ICD-10-CM codes to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
