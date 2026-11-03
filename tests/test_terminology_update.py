"""Tests for the monthly terminology update scripts (no network)."""
import datetime
import io
import json
import os
import sys
import urllib.error
import zipfile

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from scripts import download_cms_icd10 as icd  # noqa: E402
from scripts import download_rxnorm as rx  # noqa: E402

# Lines in the CMS fixed-width layouts (no tabs).
CODES_LINES = [
    "A000    Cholera due to Vibrio cholerae 01, biovar cholerae",
    "A001    Cholera due to Vibrio cholerae 01, biovar eltor",
    "S72001A Fracture of unspecified part of neck of right femur, initial encounter for closed fracture",
    "QA00101 SCN2A-related neurodevelopmental disorder",
]
ORDER_LINES = [
    "00001 A00     0 " + "Cholera".ljust(60) + " Cholera",
    "00002 A000    1 " + "Cholera due to Vibrio cholerae 01, biovar cholerae".ljust(60)
    + " Cholera due to Vibrio cholerae 01, biovar cholerae",
    "00003 A001    1 " + "Cholera due to Vibrio cholerae 01, biovar eltor".ljust(60)
    + " Cholera due to Vibrio cholerae 01, biovar eltor",
]


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, lines in files.items():
            zf.writestr(name, "\r\n".join(lines) + "\r\n")
    return buf.getvalue()


def test_fiscal_year_rolls_over_on_oct_1():
    assert icd.fiscal_year_for(datetime.date(2026, 9, 30)) == 2026
    assert icd.fiscal_year_for(datetime.date(2026, 10, 1)) == 2027
    assert icd.fiscal_year_for(datetime.date(2026, 11, 2)) == 2027


def test_candidates_use_cms_file_names():
    nov = icd.candidate_releases(datetime.date(2026, 11, 2))
    assert nov == [("2027", "https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip")]
    may = icd.candidate_releases(datetime.date(2027, 5, 2))
    assert [u for _, u in may] == [
        "https://www.cms.gov/files/zip/april-1-2027-code-descriptions-tabular-order.zip",
        "https://www.cms.gov/files/zip/2027-code-descriptions-tabular-order.zip",
    ]


def test_parses_fixed_width_codes_file():
    data = make_zip({
        "Code Descriptions/icd10cm-codes-2027.txt": CODES_LINES,
        "Code Descriptions/icd10cm-codes-addenda-2027.txt": ["Z999    should be ignored"],
        "Code Descriptions/icd10cm-order-2027.txt": ORDER_LINES,
    })
    pairs = icd.parse_zip(data)
    assert pairs[0] == ("A000", "Cholera due to Vibrio cholerae 01, biovar cholerae")
    assert pairs[2][0] == "S72001A"
    # FY2027 added codes with a letter in the second position (QA...).
    assert pairs[3] == ("QA00101", "SCN2A-related neurodevelopmental disorder")
    assert len(pairs) == 4


def test_falls_back_to_order_file_billable_only():
    data = make_zip({"icd10cm_order_2027.txt": ORDER_LINES})
    assert icd.parse_zip(data) == [
        ("A000", "Cholera due to Vibrio cholerae 01, biovar cholerae"),
        ("A001", "Cholera due to Vibrio cholerae 01, biovar eltor"),
    ]


def test_download_skips_missing_release(monkeypatch):
    good = make_zip({"icd10cm-codes-2027.txt": CODES_LINES})

    def fake_fetch(url):
        if "april-1" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return good

    monkeypatch.setattr(icd, "fetch", fake_fetch)
    label, url, data = icd.download_release(icd.candidate_releases(datetime.date(2027, 5, 2)))
    assert label == "2027" and url.endswith("2027-code-descriptions-tabular-order.zip")


def test_full_release_round_trip_matches_shipped_data(monkeypatch, tmp_path):
    shipped = json.load(open(os.path.join(ROOT, "data/terminology_parsed/icd10cm_full.json")))
    lines = [f"{e['code']:<7} {e['display']}" for e in shipped]
    monkeypatch.setattr(icd, "fetch", lambda url: make_zip({"icd10cm-codes-2027.txt": lines}))
    out = tmp_path / "icd10cm_full.json"
    assert icd.main(["--output", str(out), "--fiscal-year", "2027"]) == 0
    assert json.load(open(out)) == shipped


def test_refuses_to_write_a_tiny_file(monkeypatch, tmp_path):
    monkeypatch.setattr(icd, "fetch", lambda url: make_zip({"icd10cm-codes-2027.txt": CODES_LINES}))
    out = tmp_path / "icd10cm_full.json"
    assert icd.main(["--output", str(out), "--fiscal-year", "2027"]) == 1
    assert not out.exists()


def test_rxnorm_parses_allconcepts_response():
    response = {"minConceptGroup": {"minConcept": [
        {"rxcui": "2", "name": "Zinc", "tty": "IN"},
        {"rxcui": "1", "name": "aspirin", "tty": "IN"},
        {"rxcui": "1", "name": "aspirin", "tty": "IN"},
    ]}}
    seen = {}

    def fake_fetch(url):
        seen["url"] = url
        return response

    entries = rx.download_rxnorm(["IN", "SBD"], fetch=fake_fetch)
    assert seen["url"] == "https://rxnav.nlm.nih.gov/REST/allconcepts.json?tty=IN+SBD"
    assert [e["code"] for e in entries] == ["1", "2"]
    assert entries[0] == {"system": "RXNORM", "code": "1", "display": "aspirin",
                          "tty": "IN", "source": rx.API_SOURCE}


def test_rxnorm_keeps_non_api_entries():
    api = [{"system": "RXNORM", "code": "1", "display": "a", "tty": "IN", "source": rx.API_SOURCE}]
    existing = [
        {"system": "RXNORM", "code": "9", "display": "old api", "tty": "IN", "source": rx.API_SOURCE},
        {"system": "RXNORM", "code": "1000001", "display": "from tsv"},
        {"system": "RXNORM", "code": "1", "display": "dup of api"},
    ]
    merged, kept = rx.merge_with_existing(api, existing)
    assert kept == 1
    assert [e["code"] for e in merged] == ["1", "1000001"]


def test_rxnorm_main_refuses_empty_response(monkeypatch, tmp_path):
    monkeypatch.setattr(rx, "fetch_json", lambda url: {"minConceptGroup": {}})
    out = tmp_path / "rxnorm.json"
    assert rx.main(["--output", str(out)]) == 1
    assert not out.exists()
