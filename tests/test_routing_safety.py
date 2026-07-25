"""
Tests for the confidence-routing safety properties of the lookup engine.

These run against the SHIPPED terminology data, because the defects they cover
were properties of that data meeting that code, and a synthetic fixture would
not have reproduced either one:

  1. cdt.json carries 20 rows whose display text is just their own code
     ({"code": "D0360", "display": "D0360"}). Indexed as display text, they let
     the fuzzy matcher answer a *code* query with a different, real code — an
     unknown "D9655" scored 0.6-0.8 against them and the router forwarded that
     to a human coder as a likely mapping. Measured accuracy of every mapping
     produced that way: 0/149.

  2. The `threshold` argument was accepted by the SDK and the API and dropped on
     the floor; map_with_confidence hardcoded 0.5.

The engine fixture is module-scoped: loading 123k terms takes a couple of
seconds and none of these tests mutate it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag.rag_lookup import RAGLookup  # noqa: E402
from scripts.calibration_report import (  # noqa: E402
    MEANING_ALTERING,
    MEANING_PRESERVING,
    _perturb,
    perturbation_report,
)


@pytest.fixture(scope="module")
def rag():
    return RAGLookup()


# --------------------------------------------------------------------------
# self-referential display entries
# --------------------------------------------------------------------------

def test_self_referential_displays_are_not_indexed(rag):
    """No display key may be the code of an entry filed under it."""
    offenders = []
    for display, entries in rag.by_display.items():
        for e in entries:
            if str(e["code"]).strip().lower() == display.strip().lower():
                offenders.append((display, e["system"]))
    assert offenders == []


def test_shipped_data_still_contains_the_rows_that_were_skipped(rag):
    """
    The 20 CDT placeholder rows are excluded from the DISPLAY index only. If this
    count changes, the shipped data changed and the fix needs re-checking rather
    than the assertion being bumped.
    """
    assert rag.skipped_self_referential == 20


def test_a_skipped_entry_still_resolves_by_its_code(rag):
    """Dropping it from by_display must not make the code unlookupable."""
    result = rag.map_with_confidence(code="D0360", system="CDT")
    assert result["found"] is True
    assert result["effective_confidence"] == 1.0
    assert result["action"] == "auto_accept"


def test_is_self_referential_display_compares_case_and_whitespace_insensitively():
    assert RAGLookup._is_self_referential_display({"code": "D0360", "display": "D0360"})
    assert RAGLookup._is_self_referential_display({"code": "D0360", "display": " d0360 "})
    assert not RAGLookup._is_self_referential_display({"code": "D0360", "display": "periodic oral evaluation"})
    # An entry with no code is not self-referential, it is malformed.
    assert not RAGLookup._is_self_referential_display({"code": "", "display": ""})


# --------------------------------------------------------------------------
# absent codes must not be answered with a look-alike
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code", ["D9655", "D9841", "D9702", "D9970", "D9754", "D9386"])
def test_absent_cdt_code_is_rejected_not_substituted(rag, code):
    """
    Each of these previously came back as a different, real CDT code at 0.6-0.8
    confidence, which the router sent to `review`.
    """
    result = rag.map_with_confidence(code=code, system="CDT")
    assert result["found"] is False
    assert result["effective_confidence"] == 0.0
    assert result["action"] == "reject"
    assert result.get("source") is None


def test_absent_code_in_any_system_is_not_substituted(rag):
    """Generalisation of the above beyond the six codes that were observed."""
    for system, absent in [("CDT", "D9911"), ("ICD-10-CM", "Q77.777"), ("RXNORM", "9876543")]:
        assert ("%s|%s" % (system, absent)) not in rag.by_code, "test fixture code exists after all"
        result = rag.map_with_confidence(code=absent, system=system)
        assert result["found"] is False, "%s %s was answered with %r" % (system, absent, result.get("source"))


# --------------------------------------------------------------------------
# the display-text-in-the-code-field path still works
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["type 2 diabetes", "diabetes", "htn", "t2dm", "chest pain"])
def test_clinical_text_passed_as_code_still_resolves(rag, text):
    """
    The retry that was gated exists for callers who put a term in the code field.
    Multi-word prose, single words, and the curated abbreviations must all still
    reach it — the abbreviations especially, since t2dm/dm2 carry digits and are
    the only digit-bearing strings accepted as display text.
    """
    result = rag.map_with_confidence(code=text)
    assert result["found"] is True, "%r no longer resolves" % text


@pytest.mark.parametrize("text,expected", [
    ("chest pain", True),        # whitespace
    ("diabetes", True),          # no digits
    ("t2dm", True),              # curated abbreviation, has a digit
    ("dm2", True),               # curated abbreviation, has a digit
    ("D9655", False),            # code
    ("E11.9", False),            # code
    ("9876543", False),          # code
    ("", False),                 # nothing
])
def test_looks_like_display_text(rag, text, expected):
    assert rag.looks_like_display_text(text) is expected


# --------------------------------------------------------------------------
# the threshold argument is applied
# --------------------------------------------------------------------------

def test_threshold_filters_fuzzy_display_matches(rag):
    """
    "diabetes" matches at roughly 0.77. A threshold below that must keep it and a
    threshold above it must drop it. Before this fix every value behaved the same.
    """
    kept = rag.map_with_confidence(code="diabetes", threshold=0.5)
    assert kept["found"] is True
    conf = kept["effective_confidence"]
    assert 0.5 < conf < 1.0, "expected an interior confidence, got %r" % conf

    dropped = rag.map_with_confidence(code="diabetes", threshold=min(0.999, conf + 0.02))
    assert dropped["found"] is False
    assert dropped["action"] == "reject"


def test_threshold_does_not_touch_exact_code_hits(rag):
    """An exact hit scores 1.0 and is returned whatever the fuzzy floor is."""
    result = rag.map_with_confidence(code="E11.9", system="ICD-10-CM", threshold=0.99)
    assert result["found"] is True
    assert result["effective_confidence"] == 1.0


def test_threshold_default_matches_the_previously_hardcoded_value(rag):
    """
    The old code hardcoded 0.5. Callers who never pass the argument must see the
    same result they saw before it was wired up.
    """
    explicit = rag.map_with_confidence(code="diabetes", threshold=0.5)
    default = rag.map_with_confidence(code="diabetes")
    assert default["found"] == explicit["found"]
    assert default["effective_confidence"] == explicit["effective_confidence"]


# --------------------------------------------------------------------------
# the threshold survives the HTTP layer
#
# This is the layer the original defect lived in: the request model declared the
# field and the endpoint never passed it on. An engine-level test cannot catch
# that, so the round trip is asserted here.
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    import importlib

    from fastapi.testclient import TestClient

    os.environ["CODEBRIDGE_AUTH_DISABLED"] = "1"
    os.environ.pop("CODEBRIDGE_API_KEYS", None)
    import api.server as server_mod
    importlib.reload(server_mod)
    yield TestClient(server_mod.app)
    os.environ.pop("CODEBRIDGE_AUTH_DISABLED", None)


def test_lookup_endpoint_forwards_the_threshold(client):
    low = client.post("/lookup", json={"code": "diabetes", "threshold": 0.5})
    assert low.status_code == 200
    assert low.json()["found"] is True
    conf = low.json()["effective_confidence"]

    high = client.post("/lookup", json={"code": "diabetes", "threshold": min(0.999, conf + 0.02)})
    assert high.status_code == 200
    assert high.json()["found"] is False, "threshold is not reaching the engine"


def test_lookup_endpoint_rejects_an_out_of_range_threshold(client):
    assert client.post("/lookup", json={"code": "E11.9", "threshold": 1.5}).status_code == 422
    assert client.post("/lookup", json={"code": "E11.9", "threshold": -0.1}).status_code == 422


def test_lookup_endpoint_does_not_substitute_an_absent_code(client):
    body = client.post("/lookup", json={"code": "D9655", "system": "CDT"}).json()
    assert body["found"] is False
    assert body["action"] == "reject"


# --------------------------------------------------------------------------
# perturbation builder — pure functions, no engine needed
# --------------------------------------------------------------------------

def test_perturbation_kinds_are_disjoint():
    assert not set(MEANING_PRESERVING) & set(MEANING_ALTERING)


def test_meaning_altering_kinds_are_the_ones_that_remove_content():
    """
    Guards the labelling contract: only these two may be emitted with
    correct=null, and they must stay out of the derived-label set.
    """
    assert set(MEANING_ALTERING) == {"word_drop", "truncate"}


@pytest.mark.parametrize("kind", list(MEANING_PRESERVING) + list(MEANING_ALTERING))
def test_perturb_either_changes_the_string_or_declines(kind):
    import random
    rng = random.Random(3)
    text = "Type 2 diabetes mellitus, with hyperglycemia"
    out = _perturb(rng, text, kind)
    if out is not None:
        assert out != text
        assert out.strip() != ""


@pytest.mark.parametrize("kind,text", [
    ("punct_strip", "diabetes"),        # no punctuation to strip
    ("whitespace", "diabetes"),         # single word
    ("word_reorder", "diabetes"),       # single word
    ("word_drop", "acute pain"),        # fewer than three words
    ("truncate", "short"),              # too short to truncate
    ("typo_drop", "abc"),               # too few letters
])
def test_perturb_declines_when_inapplicable(kind, text):
    import random
    assert _perturb(random.Random(0), text, kind) is None


def test_perturb_rejects_an_unknown_kind():
    import random
    with pytest.raises(ValueError):
        _perturb(random.Random(0), "diabetes mellitus", "sprinkle_glitter")


def test_case_flip_only_changes_case():
    import random
    out = _perturb(random.Random(0), "Type 2 Diabetes", "case_flip")
    assert out == "TYPE 2 DIABETES"


def test_perturbation_report_ignores_unadjudicated_rows():
    rows = [
        {"perturbation": "typo_swap", "correct": 1, "confidence": 0.9},
        {"perturbation": "typo_swap", "correct": 0, "confidence": 0.7},
        {"perturbation": "word_drop", "correct": None, "confidence": 0.8},
    ]
    out = perturbation_report(rows)
    assert "word_drop" not in out
    # Assert the arithmetic, not just that the name appears. Checking only for
    # the presence of one label and the absence of another would still pass if
    # the report emitted a row with no counts in it at all.
    assert "typo_swap" in out
    assert "0.5000" in out, "1 correct of 2 should be reported as accuracy 0.5000"
    assert "0.8000" in out, "confidences 0.9 and 0.7 should mean 0.8000"
    typo_row = [ln for ln in out.splitlines() if "typo_swap" in ln]
    assert len(typo_row) == 1
    assert typo_row[0].split()[1] == "2", "the word_drop row must not be counted in n"


def test_perturbation_report_returns_none_when_nothing_is_labelled():
    assert perturbation_report([{"perturbation": "truncate", "correct": None, "confidence": 0.5}]) is None


# --------------------------------------------------------------------------
# perturbation builder — end to end, small
# --------------------------------------------------------------------------

def test_build_perturbation_set_labels_only_what_it_can_derive(tmp_path, rag):
    import json

    from scripts.calibration_report import build_perturbation_set

    out = tmp_path / "perturb.jsonl"
    rows = build_perturbation_set(str(out), n=27, seed=5, verbose=False)
    assert len(rows) == 27

    written = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(written) == 27

    for row in written:
        assert row["perturbation"] in set(MEANING_PRESERVING) | set(MEANING_ALTERING)
        assert row["query"]["display"] != row["expected"]["display"]
        if row["meaning_preserving"]:
            assert row["correct"] in (0, 1)
        else:
            assert row["correct"] is None, "a content-removing perturbation must not carry a derived label"


def test_build_perturbation_set_can_omit_the_unadjudicable_rows(tmp_path, rag):
    from scripts.calibration_report import build_perturbation_set

    out = tmp_path / "preserving_only.jsonl"
    rows = build_perturbation_set(str(out), n=14, seed=5, include_altering=False, verbose=False)
    assert rows
    assert all(r["correct"] in (0, 1) for r in rows)
    assert all(r["perturbation"] in MEANING_PRESERVING for r in rows)
