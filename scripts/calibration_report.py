#!/usr/bin/env python3
"""
Calibration report for the confidence score.

Answers one question: when the service reports confidence 0.80, how often is the
mapping actually right? That is what the `requires_human_review` threshold
consumes, and it is not what accuracy-by-category measures. For the
category-accuracy test see scripts/action_routing_test.py.

Reports, for a labelled set:
  - reliability table (mean confidence vs observed accuracy per bin, with 95%
    Wilson intervals, because bins are small and often saturate at 0% or 100%)
  - ECE (equal-frequency bins; bin count is printed with the number)
  - Brier score
  - AUC and overall accuracy, so ranking and calibration sit side by side
  - what accuracy each shipped decision threshold actually corresponds to
  - optionally: isotonic or Platt recalibration fitted on a split, with
    before/after ECE and Brier on the held-out half

Labelled sets are never generated from thin air. Two ways to get one:

  --build-membership-set FILE
      Builds a set whose labels come from terminology *membership*, which is a
      fact about the loaded data rather than a clinical judgement: a code that
      is present has exactly one correct entry, and a code that is present in no
      loaded system has no correct mapping at all, so any mapping returned for
      it is wrong. This measures whether the confidence score tells you that the
      thing it returned is real. It does NOT measure whether a cross-system
      mapping is clinically right.

  --build-perturbation-set FILE
      Builds a set by rewriting the display text of terms that ARE in the
      terminology — case, punctuation, a typo, a transposed word — and asking
      for them by display. The correct answer is known by construction: the
      entry the string was derived from. This is the only one of the three modes
      that puts genuine correct and incorrect mappings INSIDE the 0.6-0.95 band
      the review threshold governs, because a present code otherwise exits at an
      exact hit and an absent code has no right answer at all. Perturbations
      that remove clinical content (word_drop, truncate) can name a different
      real concept, so those rows carry correct=null and await adjudication.

  --emit-unlabelled FILE
      Runs real queries through the engine and writes rows with "correct": null
      for a human to adjudicate. Clinical correctness of a cross-system mapping
      needs a terminologist; this produces the worksheet, and the report runs on
      it once the column is filled in.

Labelled-set format, one JSON object per line:
    {"id": "...", "confidence": 0.83, "correct": 1, "query": {...}, "returned": {...}}
"correct" must be 0 or 1; rows with null are skipped and counted.

Usage:
    python3 scripts/calibration_report.py --labels my_adjudicated_set.jsonl
    python3 scripts/calibration_report.py --build-membership-set /tmp/set.jsonl
    python3 scripts/calibration_report.py --labels /tmp/set.jsonl --fit isotonic
"""

import argparse
import json
import os
import random
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from codebridge.calibration import (  # noqa: E402
    IsotonicCalibrator,
    PlattCalibrator,
    brier_score,
    expected_calibration_error,
    maximum_calibration_error,
    reliability_table,
    roc_auc,
    wilson_interval,
)

# Thresholds the shipped code actually decides on.
# rag_lookup.map_with_confidence: >=0.95 auto_accept, >=0.70 review, else reject
# codebridge.CodeBridge.lookup: threshold=0.6 default for fuzzy matches
SHIPPED_THRESHOLDS = [
    (0.60, "codebridge.lookup(threshold=) default — minimum fuzzy match kept"),
    (0.70, "review floor — below this the mapping is rejected"),
    (0.95, "auto_accept floor — at or above this no human sees the mapping"),
]


# --------------------------------------------------------------------------
# labelled set I/O
# --------------------------------------------------------------------------

def load_labelled(path):
    """Read a JSONL labelled set. Returns (confidences, labels, skipped, rows)."""
    conf, lab, rows = [], [], []
    skipped = 0
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                raise SystemExit("%s:%d: not valid JSON: %s" % (path, lineno, e))
            if "confidence" not in row:
                raise SystemExit("%s:%d: row has no 'confidence' field" % (path, lineno))
            if row.get("correct") is None:
                skipped += 1
                continue
            c = float(row["correct"])
            if c not in (0.0, 1.0):
                raise SystemExit("%s:%d: 'correct' must be 0, 1 or null, got %r" % (path, lineno, row["correct"]))
            conf.append(float(row["confidence"]))
            lab.append(int(c))
            rows.append(row)
    return conf, lab, skipped, rows


# --------------------------------------------------------------------------
# membership-labelled set builder
# --------------------------------------------------------------------------

def _absent_everywhere(rag, code):
    """True when no loaded system contains this code under any variant."""
    variants = {code, code.replace(".", "")}
    for s in rag.systems:
        variants.add(rag._normalize_code(s, code))
    for v in variants:
        for s in rag.systems:
            if "%s|%s" % (s, v) in rag.by_code:
                return False
    return True


def _synth_absent_code(rng, system):
    if system == "ICD-10-CM":
        return "%s%02d.%03d" % (rng.choice(string.ascii_uppercase), rng.randint(0, 99), rng.randint(0, 999))
    if system == "RXNORM":
        return str(rng.randint(9000000, 9999999))
    if system == "CDT":
        return "D%04d" % rng.randint(9000, 9999)
    return "%05d-%d" % (rng.randint(90000, 99999), rng.randint(0, 9))


def build_membership_set(out_path, n_positives=400, n_negatives=400, seed=1234, verbose=True):
    """
    Build a labelled set whose labels follow from terminology membership.

    Positives: codes and display strings drawn from the loaded terminology. The
    correct answer is the entry they came from, so a returned mapping is correct
    iff it is that entry (or, for a display shared by several entries, any entry
    carrying that exact display).

    Negatives: codes verified absent from every loaded system under every code
    variant the lookup tries. No correct mapping exists, so every mapping
    returned for them is incorrect, and the honest confidence is 0.

    A not-found result is recorded as confidence 0.0 with label 0: the service
    asserted nothing, and nothing was correct. It costs nothing in Brier and
    sits in the 0.0 bin of the reliability table, which is where it belongs.
    """
    from rag.rag_lookup import RAGLookup

    rag = RAGLookup()
    rng = random.Random(seed)
    keys = sorted(rag.by_code.keys())
    systems = sorted(rag.systems)
    rows = []

    n_code = n_positives // 2
    n_disp = n_positives - n_code

    for key in rng.sample(keys, min(n_code, len(keys))):
        e = rag.by_code[key]
        r = rag.map_with_confidence(code=e["code"], system=e["system"])
        src = r.get("source") or {}
        correct = int(src.get("code") == e["code"] and src.get("system") == e["system"])
        rows.append({
            "id": "pos_code:%s" % key,
            "class": "positive_known_code",
            "query": {"code": e["code"], "system": e["system"]},
            "expected": {"code": e["code"], "system": e["system"]},
            "returned": {"code": src.get("code"), "system": src.get("system"), "method": r.get("method")},
            "action": r["action"],
            "confidence": r["effective_confidence"],
            "correct": correct,
        })

    for key in rng.sample(keys, min(n_disp, len(keys))):
        e = rag.by_code[key]
        r = rag.map_with_confidence(display=e["display"])
        src = r.get("source") or {}
        same_display = [x for x in rag.by_display.get(e["display"].lower(), [])]
        correct = int(any(src.get("code") == x["code"] and src.get("system") == x["system"] for x in same_display))
        rows.append({
            "id": "pos_display:%s" % key,
            "class": "positive_known_display",
            "query": {"display": e["display"]},
            "expected": {"code": e["code"], "system": e["system"]},
            "returned": {"code": src.get("code"), "system": src.get("system"), "method": r.get("method")},
            "action": r["action"],
            "confidence": r["effective_confidence"],
            "correct": correct,
        })

    made, tries = 0, 0
    while made < n_negatives and tries < n_negatives * 200:
        tries += 1
        system = systems[made % len(systems)]
        code = _synth_absent_code(rng, system)
        if not _absent_everywhere(rag, code):
            continue
        r = rag.map_with_confidence(code=code, system=system)
        src = r.get("source") or {}
        rows.append({
            "id": "neg_absent:%s|%s" % (system, code),
            "class": "negative_absent_code",
            "query": {"code": code, "system": system},
            "expected": None,
            "returned": {"code": src.get("code"), "system": src.get("system"), "method": r.get("method")},
            "action": r["action"],
            "confidence": r["effective_confidence"],
            "correct": 0,
        })
        made += 1
        if verbose and made % 50 == 0:
            print("  ... %d/%d negatives" % (made, n_negatives), file=sys.stderr, flush=True)

    rng.shuffle(rows)
    with open(out_path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    if verbose:
        print("Wrote %d labelled rows to %s" % (len(rows), out_path), file=sys.stderr)
        print("Labels derive from terminology membership, not clinical adjudication.", file=sys.stderr)
    return rows


# --------------------------------------------------------------------------
# perturbation-labelled set builder
# --------------------------------------------------------------------------
#
# The membership set cannot say anything about the traffic the fuzzy matcher
# exists for. A code that is present exits at an exact hit with confidence 1.0,
# and a code that is absent has no correct answer at all, so every row lands at
# 1.0 or at 0.0 and the 0.6-0.95 band the router governs stays empty of real
# positives. This builder fills it: take a term that IS in the terminology,
# vary how it is written, and ask for it by display text. The correct answer is
# known by construction — it is the entry the string came from — so the labels
# are still derived rather than judged.

# Spelling changes that do not change what the term denotes. Returning a
# different concept for one of these is wrong, so the label follows.
MEANING_PRESERVING = (
    "case_flip",     # upper-case the whole term
    "punct_strip",   # drop , . - ( ) /
    "whitespace",    # double a space
    "typo_swap",     # transpose two adjacent letters
    "typo_drop",     # delete one letter
    "typo_dup",      # double one letter
    "word_reorder",  # swap two words
)

# Changes that remove clinical content. "type 2 diabetes mellitus with
# hyperglycemia" minus its last two words names a DIFFERENT real concept, and
# returning that concept is arguably the right answer to the shortened query.
# The label is therefore NOT derivable, so these rows are written with
# correct=null for a terminologist — the same discipline as emit_unlabelled.
MEANING_ALTERING = (
    "word_drop",
    "truncate",
)

_PUNCT = ",.-()/"


def _perturb(rng, text, kind):
    """
    Apply one named perturbation. Returns the new string, or None when the kind
    does not apply to this text (too short, too few words, no punctuation, no
    letters) or when it happened to be a no-op.
    """
    words = text.split()
    letters = [i for i, ch in enumerate(text) if ch.isalpha()]

    if kind == "case_flip":
        out = text.upper()
    elif kind == "punct_strip":
        if not any(ch in _PUNCT for ch in text):
            return None
        out = "".join(ch for ch in text if ch not in _PUNCT)
    elif kind == "whitespace":
        if len(words) < 2:
            return None
        i = rng.randrange(1, len(words))
        out = " ".join(words[:i]) + "  " + " ".join(words[i:])
    elif kind == "typo_swap":
        cands = [i for i in letters if i + 1 < len(text) and text[i + 1].isalpha() and text[i] != text[i + 1]]
        if not cands:
            return None
        i = rng.choice(cands)
        out = text[:i] + text[i + 1] + text[i] + text[i + 2:]
    elif kind == "typo_drop":
        if len(letters) < 6:
            return None
        i = rng.choice(letters)
        out = text[:i] + text[i + 1:]
    elif kind == "typo_dup":
        if not letters:
            return None
        i = rng.choice(letters)
        out = text[:i] + text[i] * 2 + text[i + 1:]
    elif kind == "word_reorder":
        if len(words) < 2:
            return None
        i = rng.randrange(len(words) - 1)
        w = list(words)
        w[i], w[i + 1] = w[i + 1], w[i]
        out = " ".join(w)
    elif kind == "word_drop":
        if len(words) < 3:
            return None
        i = rng.randrange(len(words))
        out = " ".join(words[:i] + words[i + 1:])
    elif kind == "truncate":
        if len(text) < 12:
            return None
        out = text[:max(8, int(len(text) * 0.7))].rstrip()
    else:
        raise ValueError("unknown perturbation kind: %r" % (kind,))

    if out.strip() == "" or out == text:
        return None
    return out


def build_perturbation_set(out_path, n=600, seed=1234, min_display_len=10,
                           include_altering=True, verbose=True):
    """
    Build a labelled set from surface variations of terms that are really there.

    For each row: pick a loaded entry with real display text, rewrite its display
    with one named perturbation, and query the engine by display. A row is
    correct when the engine comes back with the entry the string was derived from
    — or with any entry carrying that same display, since a display shared by
    several codes cannot be disambiguated from the text alone.

    Meaning-preserving perturbations get a derived 0/1 label. Meaning-altering
    ones (word_drop, truncate) get correct=null, because a shorter term can name
    a genuinely different concept and only a terminologist can say whether the
    answer was right. They are still emitted, with their kind recorded, so the
    worksheet is there when someone wants to adjudicate it.

    SCOPE LIMIT: this measures whether display retrieval survives how a term is
    written. It does not measure clinical correctness of a cross-system mapping.
    """
    from rag.rag_lookup import RAGLookup

    rag = RAGLookup()
    rng = random.Random(seed)

    kinds = list(MEANING_PRESERVING) + (list(MEANING_ALTERING) if include_altering else [])

    # Only entries whose display is real text, long enough to perturb. The
    # display index already excludes rows whose display is just their own code.
    usable = [k for k, e in rag.by_code.items()
              if e["display"].lower() in rag.by_display and len(e["display"]) >= min_display_len]
    usable.sort()
    if not usable:
        raise SystemExit("no entries with display text of at least %d chars" % min_display_len)

    rows = []
    attempts = 0
    while len(rows) < n and attempts < n * 60:
        attempts += 1
        e = rag.by_code[usable[rng.randrange(len(usable))]]
        kind = kinds[len(rows) % len(kinds)]
        query = _perturb(rng, e["display"], kind)
        if query is None:
            continue

        r = rag.map_with_confidence(display=query)
        src = r.get("source") or {}
        same_display = rag.by_display.get(e["display"].lower(), [])
        hit = any(src.get("code") == x["code"] and src.get("system") == x["system"] for x in same_display)

        preserving = kind in MEANING_PRESERVING
        rows.append({
            "id": "perturb:%s|%s:%s" % (e["system"], e["code"], kind),
            "class": "perturbed_display_preserving" if preserving else "perturbed_display_altering",
            "perturbation": kind,
            "meaning_preserving": preserving,
            "query": {"display": query},
            "expected": {"code": e["code"], "system": e["system"], "display": e["display"]},
            "returned": {"code": src.get("code"), "system": src.get("system"),
                         "display": src.get("display"), "method": r.get("method")},
            "action": r["action"],
            "confidence": r["effective_confidence"],
            "correct": int(hit) if preserving else None,
        })
        if verbose and len(rows) % 100 == 0:
            print("  ... %d/%d rows" % (len(rows), n), file=sys.stderr, flush=True)

    rng.shuffle(rows)
    with open(out_path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    if verbose:
        labelled = sum(1 for r in rows if r["correct"] is not None)
        print("Wrote %d rows to %s (%d labelled, %d await adjudication)" % (
            len(rows), out_path, labelled, len(rows) - labelled), file=sys.stderr)
        print("Labels derive from which entry the query string was built from,", file=sys.stderr)
        print("not from clinical adjudication of a cross-system mapping.", file=sys.stderr)
    return rows


def perturbation_report(rows):
    """Accuracy per perturbation kind — the stratum a pooled metric hides."""
    by_kind = {}
    for r in rows:
        if r.get("correct") is None or "perturbation" not in r:
            continue
        k = r["perturbation"]
        s = by_kind.setdefault(k, {"n": 0, "correct": 0, "conf": 0.0})
        s["n"] += 1
        s["correct"] += int(r["correct"])
        s["conf"] += float(r["confidence"])
    if not by_kind:
        return None
    out = ["  perturbation        n   mean conf   accuracy   95% CI", "  " + "-" * 64]
    for k in sorted(by_kind, key=lambda k: by_kind[k]["correct"] / by_kind[k]["n"]):
        s = by_kind[k]
        lo, hi = wilson_interval(s["correct"], s["n"])
        out.append("  %-16s %5d      %.4f     %.4f   [%.3f, %.3f]" % (
            k, s["n"], s["conf"] / s["n"], s["correct"] / s["n"], lo, hi))
    return "\n".join(out)


def emit_unlabelled(out_path, n=200, seed=1234, verbose=True):
    """
    Write real cross-system mappings with "correct": null for human adjudication.

    Cross-system clinical correctness cannot be derived from the data — a
    terminologist has to read each row. This produces the worksheet.
    """
    from rag.rag_lookup import RAGLookup

    rag = RAGLookup()
    rng = random.Random(seed)
    sources = sorted(rag.crosswalk.keys())
    rng.shuffle(sources)
    written = 0
    with open(out_path, "w") as f:
        for s in sources:
            if written >= n:
                break
            uri, code = s.rsplit("|", 1)
            system = rag.URI_TO_SYSTEM.get(uri, uri)
            r = rag.map_with_confidence(code=code, system=system)
            for t in r.get("targets", []):
                if written >= n:
                    break
                f.write(json.dumps({
                    "id": "cw:%s->%s|%s" % (s, t["system"], t["code"]),
                    "class": "crosswalk_target",
                    "query": {"code": code, "system": system},
                    "returned": {"code": t["code"], "system": t["system"],
                                 "display": t["display"], "method": t["method"]},
                    "confidence": t["confidence"],
                    "action": r["action"],
                    "correct": None,
                }) + "\n")
                written += 1
    if verbose:
        print("Wrote %d unlabelled rows to %s" % (written, out_path), file=sys.stderr)
        print('Set "correct" to 0 or 1 on each row, then re-run with --labels.', file=sys.stderr)
    return written


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def format_reliability(rows):
    out = []
    out.append("  bin      n   conf range        mean conf   observed acc   95% CI            gap")
    out.append("  " + "-" * 88)
    for r in rows:
        out.append("  %3d  %5d   [%.3f, %.3f]      %.4f      %5d/%-5d %.4f   [%.3f, %.3f]   %+.4f" % (
            r["bin"], r["n"], r["conf_min"], r["conf_max"], r["conf_mean"],
            r["correct"], r["n"], r["accuracy"], r["acc_ci_lo"], r["acc_ci_hi"], r["gap"]))
    return "\n".join(out)


def threshold_report(conf, lab):
    out = []
    out.append("  threshold   n at/above   accuracy at/above   95% CI            meaning")
    out.append("  " + "-" * 96)
    for t, why in SHIPPED_THRESHOLDS:
        idx = [i for i in range(len(conf)) if conf[i] >= t]
        if not idx:
            out.append("  %.2f        %5d       (no rows)                             %s" % (t, 0, why))
            continue
        k = sum(lab[i] for i in idx)
        lo, hi = wilson_interval(k, len(idx))
        out.append("  %.2f        %5d           %5d/%-5d %.4f  [%.3f, %.3f]   %s" % (
            t, len(idx), k, len(idx), k / len(idx), lo, hi, why))
    return "\n".join(out)


def band_report(conf, lab):
    bands = [(0.0, 0.60), (0.60, 0.70), (0.70, 0.95), (0.95, 1.0001)]
    names = ["< 0.60 (dropped by the SDK filter)", "0.60-0.70 (kept by filter, rejected by router)",
             "0.70-0.95 (review)", ">= 0.95 (auto_accept, no human)"]
    out = ["  band                                              n   accuracy   95% CI", "  " + "-" * 78]
    for (lo_t, hi_t), name in zip(bands, names):
        idx = [i for i in range(len(conf)) if lo_t <= conf[i] < hi_t]
        if not idx:
            out.append("  %-46s %5d   --" % (name, 0))
            continue
        k = sum(lab[i] for i in idx)
        lo, hi = wilson_interval(k, len(idx))
        out.append("  %-46s %5d   %.4f     [%.3f, %.3f]" % (name, len(idx), k / len(idx), lo, hi))
    return "\n".join(out)


def summarise(conf, lab, n_bins, strategy="quantile"):
    auc = roc_auc(conf, lab)
    return {
        "n": len(conf),
        "base_rate": sum(lab) / len(lab),
        "mean_confidence": sum(conf) / len(conf),
        "accuracy": sum(lab) / len(lab),
        "brier": brier_score(conf, lab),
        "ece": expected_calibration_error(conf, lab, n_bins=n_bins, strategy=strategy),
        "mce": maximum_calibration_error(conf, lab, n_bins=n_bins, strategy=strategy),
        "auc": auc,
        "n_bins_requested": n_bins,
        "n_bins_used": len(reliability_table(conf, lab, n_bins=n_bins, strategy=strategy)),
    }


def main():
    ap = argparse.ArgumentParser(description="Calibration report for the confidence score")
    ap.add_argument("--labels", help="JSONL labelled set")
    ap.add_argument("--build-membership-set", metavar="OUT",
                    help="build a membership-labelled set and write it here")
    ap.add_argument("--build-perturbation-set", metavar="OUT",
                    help="build a set from surface variations of real terms and write it here")
    ap.add_argument("--emit-unlabelled", metavar="OUT",
                    help="write real mappings with correct=null for human adjudication")
    ap.add_argument("--n-positives", type=int, default=400)
    ap.add_argument("--n-negatives", type=int, default=400)
    ap.add_argument("--n-perturbations", type=int, default=600,
                    help="row count for --build-perturbation-set")
    ap.add_argument("--no-meaning-altering", action="store_true",
                    help="omit word_drop/truncate rows, which need adjudication")
    ap.add_argument("--n", type=int, default=200, help="row count for --emit-unlabelled")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--bins", type=int, default=10, help="equal-frequency bins for ECE")
    ap.add_argument("--strategy", choices=["quantile", "uniform"], default="quantile")
    ap.add_argument("--fit", choices=["none", "isotonic", "platt"], default="none")
    ap.add_argument("--split-frac", type=float, default=0.5, help="fraction used to fit the calibrator")
    ap.add_argument("--json", metavar="OUT", help="write the report as JSON")
    args = ap.parse_args()

    if args.build_membership_set:
        build_membership_set(args.build_membership_set, args.n_positives, args.n_negatives, args.seed)
        if not args.labels:
            args.labels = args.build_membership_set

    if args.build_perturbation_set:
        build_perturbation_set(args.build_perturbation_set, args.n_perturbations, args.seed,
                               include_altering=not args.no_meaning_altering)
        if not args.labels:
            args.labels = args.build_perturbation_set

    if args.emit_unlabelled:
        emit_unlabelled(args.emit_unlabelled, args.n, args.seed)
        if not args.labels:
            return 0

    if not args.labels:
        sys.stderr.write(__doc__)
        sys.stderr.write("\nNo labelled set given. This script will not invent one.\n")
        return 2

    conf, lab, skipped, rows = load_labelled(args.labels)
    if not conf:
        sys.stderr.write("No labelled rows in %s (%d rows had correct=null).\n" % (args.labels, skipped))
        return 2

    print("=" * 92)
    print("CALIBRATION REPORT — is the shipped confidence a probability?")
    print("=" * 92)
    print("Labelled set: %s" % args.labels)
    print("  rows scored: %d   (skipped, correct=null: %d)" % (len(conf), skipped))
    classes = {}
    for r in rows:
        classes[r.get("class", "unspecified")] = classes.get(r.get("class", "unspecified"), 0) + 1
    for k in sorted(classes):
        print("    %-28s %5d" % (k, classes[k]))

    overall = summarise(conf, lab, args.bins, args.strategy)
    print("\nHeadline")
    print("-" * 92)
    print("  n                  %d" % overall["n"])
    print("  base rate correct  %.4f" % overall["base_rate"])
    print("  mean confidence    %.4f" % overall["mean_confidence"])
    print("  ECE                %.5f   (%s bins requested %d, used %d)" % (
        overall["ece"], args.strategy, overall["n_bins_requested"], overall["n_bins_used"]))
    print("  MCE                %.5f" % overall["mce"])
    print("  Brier              %.5f" % overall["brier"])
    print("  AUC                %s   (ranking; unchanged by a monotone calibrator)" % (
        "%.5f" % overall["auc"] if overall["auc"] is not None else "undefined (one class only)"))
    if overall["n_bins_used"] < args.bins:
        print("  note: fewer bins than requested — the score piles up on repeated values,")
        print("        and tied values are never split across bins.")

    print("\nReliability table (%s bins)" % args.strategy)
    print("-" * 92)
    print(format_reliability(reliability_table(conf, lab, n_bins=args.bins, strategy=args.strategy)))
    print("  gap = mean confidence - observed accuracy. Positive means overconfident.")

    print("\nWhat the shipped decision thresholds actually buy")
    print("-" * 92)
    print(threshold_report(conf, lab))
    print("\nAccuracy inside each routing band")
    print("-" * 92)
    print(band_report(conf, lab))

    report = {"labelled_set": str(args.labels), "classes": classes, "overall": overall,
              "reliability": reliability_table(conf, lab, n_bins=args.bins, strategy=args.strategy)}

    per_kind = perturbation_report(rows)
    if per_kind:
        print("\nAccuracy per perturbation — the stratum a pooled metric hides")
        print("-" * 92)
        print(per_kind)

    if args.fit != "none":
        rng = random.Random(args.seed)
        idx = list(range(len(conf)))
        rng.shuffle(idx)
        cut = int(len(idx) * args.split_frac)
        fit_i, hold_i = idx[:cut], idx[cut:]
        if not fit_i or not hold_i:
            print("\nSplit produced an empty half — not fitting.")
            return 0
        cal = IsotonicCalibrator() if args.fit == "isotonic" else PlattCalibrator()
        cal.fit([conf[i] for i in fit_i], [lab[i] for i in fit_i])
        h_conf = [conf[i] for i in hold_i]
        h_lab = [lab[i] for i in hold_i]
        h_cal = cal.predict(h_conf)
        before = summarise(h_conf, h_lab, args.bins, args.strategy)
        after = summarise(h_cal, h_lab, args.bins, args.strategy)
        print("\n%s recalibration — fitted on %d rows, evaluated on %d held out" % (
            args.fit, len(fit_i), len(hold_i)))
        print("-" * 92)
        print("  metric        before      after       change")
        print("  ECE          %.5f     %.5f    %+.5f" % (before["ece"], after["ece"], after["ece"] - before["ece"]))
        print("  Brier        %.5f     %.5f    %+.5f" % (before["brier"], after["brier"], after["brier"] - before["brier"]))
        b_auc = before["auc"] if before["auc"] is not None else float("nan")
        a_auc = after["auc"] if after["auc"] is not None else float("nan")
        print("  AUC          %.5f     %.5f    %+.5f   (a monotone map cannot improve ranking, and"
              % (b_auc, a_auc, a_auc - b_auc))
        print("                                              lowers AUC when it merges distinct scores into ties)")
        print("\n  Calibrator (apply as a lookup, no library needed):")
        print("  " + json.dumps(cal.to_dict())[:400])
        report["calibration_fit"] = {"kind": args.fit, "n_fit": len(fit_i), "n_holdout": len(hold_i),
                                     "before": before, "after": after, "calibrator": cal.to_dict()}

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json, "w") as f:
            json.dump(report, f, indent=2)
        print("\nJSON written to %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
