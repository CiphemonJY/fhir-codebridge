"""
Tests for codebridge.calibration.

These use constructed inputs with hand-computable answers. That is deliberate:
they check the metric implementation, not the service's confidence score. The
service's own calibration can only be measured against an adjudicated set of
real mappings — see scripts/calibration_report.py.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codebridge.calibration import (
    IsotonicCalibrator,
    PlattCalibrator,
    brier_score,
    expected_calibration_error,
    maximum_calibration_error,
    reliability_table,
    roc_auc,
    wilson_interval,
)


# --------------------------------------------------------------------------
# Brier
# --------------------------------------------------------------------------

def test_brier_perfect_prediction_is_zero():
    assert brier_score([1.0, 0.0, 1.0], [1, 0, 1]) == 0.0


def test_brier_worst_case_is_one():
    assert brier_score([1.0, 0.0], [0, 1]) == 1.0


def test_brier_hand_computed():
    # (0.8-1)^2 + (0.6-0)^2 + (0.5-1)^2 = 0.04 + 0.36 + 0.25 = 0.65, /3
    assert brier_score([0.8, 0.6, 0.5], [1, 0, 1]) == pytest.approx(0.65 / 3)


def test_brier_constant_half_is_quarter():
    assert brier_score([0.5] * 8, [1, 0, 1, 0, 1, 0, 1, 0]) == pytest.approx(0.25)


# --------------------------------------------------------------------------
# reliability / ECE
# --------------------------------------------------------------------------

def test_perfectly_calibrated_score_has_zero_ece():
    # Two confidence levels, each matched exactly by observed frequency.
    conf = [0.25] * 100 + [0.75] * 100
    lab = [1] * 25 + [0] * 75 + [1] * 75 + [0] * 25
    assert expected_calibration_error(conf, lab, n_bins=2) == pytest.approx(0.0, abs=1e-12)


def test_overconfident_score_has_ece_equal_to_the_gap():
    # Always says 0.9, right 60% of the time -> ECE 0.30, and it is overconfident.
    conf = [0.9] * 100
    lab = [1] * 60 + [0] * 40
    assert expected_calibration_error(conf, lab, n_bins=10) == pytest.approx(0.30)
    rows = reliability_table(conf, lab, n_bins=10)
    assert len(rows) == 1
    assert rows[0]["gap"] == pytest.approx(0.30)


def test_ece_is_sample_weighted_across_bins():
    # 90 rows with gap 0.1, 10 rows with gap 0.5 -> 0.9*0.1 + 0.1*0.5 = 0.14
    conf = [0.9] * 90 + [0.5] * 10
    lab = [1] * 72 + [0] * 18 + [1] * 10
    assert expected_calibration_error(conf, lab, n_bins=2) == pytest.approx(0.14)
    assert maximum_calibration_error(conf, lab, n_bins=2) == pytest.approx(0.5)


def test_equal_frequency_bins_are_balanced_when_values_are_distinct():
    conf = [i / 1000.0 for i in range(1000)]
    lab = [i % 2 for i in range(1000)]
    rows = reliability_table(conf, lab, n_bins=10)
    assert len(rows) == 10
    assert [r["n"] for r in rows] == [100] * 10


def test_tied_values_are_never_split_across_bins():
    # This score is degenerate on 1.0, exactly like an exact-code lookup. A bin
    # boundary inside the tie would invent a distinction the score cannot make.
    conf = [1.0] * 95 + [0.3] * 5
    lab = [1] * 95 + [0] * 5
    rows = reliability_table(conf, lab, n_bins=10)
    assert len(rows) == 2
    assert sorted(r["n"] for r in rows) == [5, 95]
    for r in rows:
        assert r["conf_min"] == r["conf_max"]


def test_reliability_bins_partition_the_input():
    conf = [0.1, 0.4, 0.4, 0.7, 0.9, 0.95, 0.2, 0.8]
    lab = [0, 1, 0, 1, 1, 1, 0, 1]
    rows = reliability_table(conf, lab, n_bins=4)
    assert sum(r["n"] for r in rows) == len(conf)
    assert sum(r["correct"] for r in rows) == sum(lab)
    # bins are ordered and non-overlapping
    for a, b in zip(rows, rows[1:]):
        assert a["conf_max"] <= b["conf_min"]


def test_uniform_strategy_uses_fixed_width_bins():
    conf = [0.05, 0.15, 0.95]
    lab = [0, 0, 1]
    rows = reliability_table(conf, lab, n_bins=10, strategy="uniform")
    assert [r["n"] for r in rows] == [1, 1, 1]


def test_ece_rejects_bad_input():
    with pytest.raises(ValueError):
        expected_calibration_error([0.5, 0.5], [1])
    with pytest.raises(ValueError):
        expected_calibration_error([1.5], [1])
    with pytest.raises(ValueError):
        expected_calibration_error([0.5], [2])
    with pytest.raises(ValueError):
        expected_calibration_error([], [])


# --------------------------------------------------------------------------
# Wilson interval — the honest error bar on a small bin
# --------------------------------------------------------------------------

def test_wilson_interval_is_wide_for_a_small_perfect_bin():
    lo, hi = wilson_interval(10, 10)
    assert hi == pytest.approx(1.0, abs=1e-9)
    assert lo < 0.75  # 10/10 does not mean 100%


def test_wilson_interval_narrows_with_more_data():
    lo_small, hi_small = wilson_interval(50, 100)
    lo_big, hi_big = wilson_interval(5000, 10000)
    assert (hi_big - lo_big) < (hi_small - lo_small)


def test_wilson_interval_brackets_the_point_estimate():
    for k, n in [(0, 7), (3, 7), (7, 7), (1, 1000)]:
        lo, hi = wilson_interval(k, n)
        assert lo <= k / n + 1e-12
        assert k / n <= hi + 1e-12


# --------------------------------------------------------------------------
# AUC — ranking, which calibration does not touch
# --------------------------------------------------------------------------

def test_auc_perfect_separation():
    assert roc_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == pytest.approx(1.0)


def test_auc_inverted_separation():
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == pytest.approx(0.0)


def test_auc_all_ties_is_one_half():
    assert roc_auc([0.5] * 6, [1, 0, 1, 0, 1, 0]) == pytest.approx(0.5)


def test_auc_undefined_with_a_single_class():
    assert roc_auc([0.2, 0.4, 0.9], [1, 1, 1]) is None


def test_auc_is_invariant_to_monotone_rescaling():
    conf = [0.05, 0.3, 0.31, 0.7, 0.99]
    lab = [0, 0, 1, 0, 1]
    squashed = [c ** 3 for c in conf]
    assert roc_auc(conf, lab) == pytest.approx(roc_auc(squashed, lab))


# --------------------------------------------------------------------------
# Isotonic
# --------------------------------------------------------------------------

def test_isotonic_fixes_a_systematically_overconfident_score():
    # Score always says 0.9 but is right 60% of the time.
    conf = [0.9] * 200
    lab = [1] * 120 + [0] * 80
    cal = IsotonicCalibrator().fit(conf, lab)
    assert cal.predict_one(0.9) == pytest.approx(0.6)
    before = expected_calibration_error(conf, lab, n_bins=5)
    after = expected_calibration_error(cal.predict(conf), lab, n_bins=5)
    assert before == pytest.approx(0.3)
    assert after == pytest.approx(0.0, abs=1e-12)


def test_isotonic_lowers_brier_or_leaves_it_alone_on_its_own_fit():
    conf = [i / 100.0 for i in range(100)]
    lab = [1 if (i / 100.0) > 0.7 else 0 for i in range(100)]
    cal = IsotonicCalibrator().fit(conf, lab)
    assert brier_score(cal.predict(conf), lab) <= brier_score(conf, lab) + 1e-12


def test_isotonic_output_is_non_decreasing():
    conf = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    lab = [0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1]
    cal = IsotonicCalibrator().fit(conf, lab)
    grid = [i / 50.0 for i in range(51)]
    out = cal.predict(grid)
    for a, b in zip(out, out[1:]):
        assert b >= a - 1e-12


def test_isotonic_never_inverts_ranking():
    # The point of preferring isotonic: it is non-decreasing, so it can change
    # what a score means but never turn a higher-scoring mapping into a
    # lower-scoring one. It can merge two scores into a tie, which is why AUC is
    # allowed to rise but not to fall.
    conf = [0.10, 0.25, 0.30, 0.55, 0.60, 0.80, 0.90, 0.95]
    lab = [0, 0, 1, 0, 1, 1, 0, 1]
    cal = IsotonicCalibrator().fit(conf, lab)
    assert roc_auc(cal.predict(conf), lab) >= roc_auc(conf, lab) - 1e-12
    for a, b in zip(conf, conf[1:]):
        if a < b:
            assert cal.predict_one(a) <= cal.predict_one(b) + 1e-12


def test_a_strictly_monotone_calibrator_leaves_auc_untouched():
    conf = [0.10, 0.25, 0.30, 0.55, 0.60, 0.80, 0.90, 0.95]
    lab = [0, 0, 1, 0, 1, 1, 0, 1]
    cal = PlattCalibrator().fit(conf, lab)
    assert roc_auc(cal.predict(conf), lab) == pytest.approx(roc_auc(conf, lab))


def test_isotonic_pools_adjacent_violators():
    # y decreases between x=0.4 and x=0.6, so those two must be pooled to 0.5.
    cal = IsotonicCalibrator().fit([0.2, 0.4, 0.6, 0.8], [0, 1, 0, 1])
    assert cal.predict_one(0.4) == pytest.approx(0.5)
    assert cal.predict_one(0.6) == pytest.approx(0.5)
    assert cal.predict_one(0.2) == pytest.approx(0.0)
    assert cal.predict_one(0.8) == pytest.approx(1.0)


def test_isotonic_clips_outside_the_fitted_range():
    cal = IsotonicCalibrator().fit([0.4, 0.6], [0, 1])
    assert cal.predict_one(0.0) == pytest.approx(0.0)
    assert cal.predict_one(1.0) == pytest.approx(1.0)


def test_isotonic_interpolates_between_fitted_points():
    cal = IsotonicCalibrator().fit([0.0, 1.0], [0, 1])
    assert cal.predict_one(0.5) == pytest.approx(0.5)


def test_isotonic_round_trips_through_a_plain_dict():
    cal = IsotonicCalibrator().fit([0.1, 0.5, 0.9], [0, 1, 1])
    payload = cal.to_dict()
    assert payload["kind"] == "isotonic"
    restored = IsotonicCalibrator.from_dict(payload)
    grid = [i / 20.0 for i in range(21)]
    assert restored.predict(grid) == pytest.approx(cal.predict(grid))


def test_unfitted_calibrator_refuses_to_predict():
    with pytest.raises(RuntimeError):
        IsotonicCalibrator().predict_one(0.5)
    with pytest.raises(RuntimeError):
        PlattCalibrator().predict_one(0.5)


def test_from_dict_rejects_the_wrong_kind():
    with pytest.raises(ValueError):
        IsotonicCalibrator.from_dict({"kind": "platt", "a": 1.0, "b": 0.0})
    with pytest.raises(ValueError):
        PlattCalibrator.from_dict({"kind": "isotonic", "x": [0.0], "y": [0.0]})


# --------------------------------------------------------------------------
# Platt
# --------------------------------------------------------------------------

def test_platt_recovers_an_increasing_relationship():
    conf = [i / 200.0 for i in range(200)]
    lab = [1 if i >= 100 else 0 for i in range(200)]
    cal = PlattCalibrator().fit(conf, lab)
    assert cal.a > 0
    assert cal.predict_one(0.9) > cal.predict_one(0.1)


def test_platt_output_stays_in_the_unit_interval():
    cal = PlattCalibrator().fit([0.0, 0.5, 1.0], [0, 1, 1])
    for x in [0.0, 0.25, 0.5, 0.75, 1.0]:
        p = cal.predict_one(x)
        assert 0.0 <= p <= 1.0


def test_platt_reduces_ece_on_an_overconfident_score():
    conf = [0.95] * 60 + [0.9] * 60
    lab = [1] * 36 + [0] * 24 + [1] * 30 + [0] * 30
    cal = PlattCalibrator().fit(conf, lab)
    assert expected_calibration_error(cal.predict(conf), lab, n_bins=2) < \
        expected_calibration_error(conf, lab, n_bins=2)


def test_platt_survives_a_single_class():
    # Platt's prior correction keeps this finite instead of diverging.
    cal = PlattCalibrator().fit([0.2, 0.5, 0.8], [1, 1, 1])
    assert all(math.isfinite(p) for p in cal.predict([0.0, 0.5, 1.0]))


def test_platt_round_trips_through_a_plain_dict():
    cal = PlattCalibrator().fit([0.1, 0.4, 0.9], [0, 1, 1])
    restored = PlattCalibrator.from_dict(cal.to_dict())
    assert restored.predict([0.2, 0.7]) == pytest.approx(cal.predict([0.2, 0.7]))


# --------------------------------------------------------------------------
# scripts/calibration_report.py — labelled-set handling
#
# The report must never quietly turn an unlabelled or malformed row into a
# label, so these check that it skips or refuses instead.
# --------------------------------------------------------------------------

from scripts.calibration_report import (  # noqa: E402
    SHIPPED_THRESHOLDS,
    band_report,
    load_labelled,
    threshold_report,
)


def _write(tmp_path, lines):
    p = tmp_path / "set.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_load_labelled_reads_scored_rows(tmp_path):
    path = _write(tmp_path, [
        '{"id": "a", "confidence": 0.8, "correct": 1}',
        '{"id": "b", "confidence": 0.2, "correct": 0}',
    ])
    conf, lab, skipped, rows = load_labelled(path)
    assert conf == [0.8, 0.2]
    assert lab == [1, 0]
    assert skipped == 0
    assert len(rows) == 2


def test_load_labelled_skips_unadjudicated_rows_and_counts_them(tmp_path):
    path = _write(tmp_path, [
        '{"id": "a", "confidence": 0.8, "correct": 1}',
        '{"id": "b", "confidence": 0.9, "correct": null}',
        '{"id": "c", "confidence": 0.9}',
    ])
    conf, lab, skipped, rows = load_labelled(path)
    assert conf == [0.8]
    assert skipped == 2


def test_load_labelled_ignores_blank_and_comment_lines(tmp_path):
    path = _write(tmp_path, [
        "# a worksheet header",
        "",
        '{"id": "a", "confidence": 0.5, "correct": 0}',
    ])
    conf, lab, skipped, _ = load_labelled(path)
    assert conf == [0.5] and lab == [0] and skipped == 0


def test_load_labelled_refuses_a_row_without_confidence(tmp_path):
    path = _write(tmp_path, ['{"id": "a", "correct": 1}'])
    with pytest.raises(SystemExit):
        load_labelled(path)


def test_load_labelled_refuses_a_non_binary_label(tmp_path):
    path = _write(tmp_path, ['{"id": "a", "confidence": 0.5, "correct": 2}'])
    with pytest.raises(SystemExit):
        load_labelled(path)


def test_load_labelled_refuses_malformed_json(tmp_path):
    path = _write(tmp_path, ['{"id": "a", "confidence": 0.5,}'])
    with pytest.raises(SystemExit):
        load_labelled(path)


def test_shipped_thresholds_cover_the_routing_decisions():
    # 0.70 and 0.95 are the routing floors in rag_lookup.map_with_confidence;
    # 0.60 is the client and API default. If any of those move, the report has
    # to move with them or it stops describing the shipped behaviour.
    assert [t for t, _ in SHIPPED_THRESHOLDS] == [0.60, 0.70, 0.95]


def test_band_report_accounts_for_every_row():
    import re
    conf = [0.0, 0.65, 0.8, 1.0, 1.0]
    lab = [0, 0, 0, 1, 1]
    band = band_report(conf, lab)
    for name in ["< 0.60", "0.60-0.70", "0.70-0.95", ">= 0.95"]:
        assert name in band
    counted = re.findall(r"\s(\d+)\s+([01]\.\d{4})\s+\[", band)
    assert sum(int(n) for n, _ in counted) == len(conf)


def test_threshold_report_counts_rows_at_or_above_each_threshold():
    conf = [0.0, 0.65, 0.8, 1.0, 1.0]
    lab = [0, 0, 0, 1, 1]
    thr = threshold_report(conf, lab)
    # 4 rows are >= 0.60, 3 are >= 0.70, 2 are >= 0.95
    lines = [l for l in thr.splitlines() if l.strip().startswith("0.")]
    assert len(lines) == 3
    assert lines[0].split()[1] == "4"
    assert lines[1].split()[1] == "3"
    assert lines[2].split()[1] == "2"
