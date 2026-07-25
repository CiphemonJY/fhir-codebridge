#!/usr/bin/env python3
"""
Calibration metrics for confidence scores.

A confidence score is *calibrated* when it matches observed frequency: of the
mappings emitted at confidence 0.80, about 80% should be correct. Calibration is
separate from ranking. A score can order candidates perfectly (high AUC) and
still be badly calibrated, and a threshold decision — such as routing a mapping
to human review — consumes the calibration, not the ranking.

Pure standard library: no numpy, scipy, or scikit-learn, so this imports in the
same minimal environment the service runs in.

Inputs everywhere are two parallel sequences:
    confidences: floats in [0, 1]
    labels:      1 if the mapping was correct, 0 if it was not

Nothing here invents labels. The caller supplies an adjudicated set.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "brier_score",
    "reliability_table",
    "expected_calibration_error",
    "maximum_calibration_error",
    "roc_auc",
    "wilson_interval",
    "IsotonicCalibrator",
    "PlattCalibrator",
]


def _check(confidences: Sequence[float], labels: Sequence[int]) -> Tuple[List[float], List[int]]:
    c = [float(x) for x in confidences]
    y = [int(x) for x in labels]
    if len(c) != len(y):
        raise ValueError("confidences and labels must be the same length (%d != %d)" % (len(c), len(y)))
    if not c:
        raise ValueError("empty input: nothing to measure")
    for v in c:
        if not (0.0 <= v <= 1.0) or math.isnan(v):
            raise ValueError("confidence out of range [0,1]: %r" % (v,))
    for v in y:
        if v not in (0, 1):
            raise ValueError("label must be 0 or 1, got %r" % (v,))
    return c, y


def brier_score(confidences: Sequence[float], labels: Sequence[int]) -> float:
    """Mean squared error between confidence and outcome. Lower is better."""
    c, y = _check(confidences, labels)
    return sum((ci - yi) ** 2 for ci, yi in zip(c, y)) / len(c)


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> Tuple[float, float]:
    """
    Wilson score interval for a binomial proportion (default 95%).

    Used instead of the normal approximation because calibration bins are often
    small and frequently hit 0% or 100%, where the normal interval has zero
    width and lies about the uncertainty.
    """
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    halfwidth = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - halfwidth), min(1.0, centre + halfwidth))


def _equal_frequency_groups(c: Sequence[float], n_bins: int) -> List[List[int]]:
    """
    Split indices into ~equal-count bins by confidence, never splitting ties.

    Confidence scores in terminology mapping pile up on a few exact values
    (1.0 for an exact hit, 0.0 for no match). Splitting a tied value across two
    bins would manufacture a difference between bins that the score cannot
    express, so tied values always land in the same bin: whole tie groups are
    packed into a bin, and a group joins the bin only while doing so gets the
    bin closer to its target size. Consequence: with heavy ties you get fewer
    than n_bins bins and the bins are not equal size. That is reported rather
    than hidden.
    """
    buckets: Dict[float, List[int]] = {}
    for i, v in enumerate(c):
        buckets.setdefault(v, []).append(i)
    tie_groups = [buckets[v] for v in sorted(buckets)]

    groups: List[List[int]] = []
    g = 0
    while g < len(tie_groups) and len(groups) < n_bins:
        bins_left = n_bins - len(groups)
        items_left = sum(len(tg) for tg in tie_groups[g:])
        target = items_left / float(bins_left)
        current: List[int] = []
        while g < len(tie_groups):
            if current and abs(len(current) + len(tie_groups[g]) - target) > abs(len(current) - target):
                break
            current.extend(tie_groups[g])
            g += 1
            # Leave one tie group for each remaining bin.
            if bins_left > 1 and (len(tie_groups) - g) == (bins_left - 1):
                break
        groups.append(current)
    while g < len(tie_groups):
        groups[-1].extend(tie_groups[g])
        g += 1
    return groups


def _equal_width_groups(c: Sequence[float], n_bins: int) -> List[List[int]]:
    groups: List[List[int]] = [[] for _ in range(n_bins)]
    for i, v in enumerate(c):
        b = min(int(v * n_bins), n_bins - 1)
        groups[b].append(i)
    return [g for g in groups if g]


def reliability_table(
    confidences: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: str = "quantile",
) -> List[Dict[str, float]]:
    """
    Predicted confidence vs observed accuracy, per bin.

    strategy: "quantile" for equal-frequency bins (default; ties kept together)
              "uniform"  for equal-width bins
    Returns one dict per non-empty bin with n, confidence range, mean
    confidence, observed accuracy, a 95% Wilson interval on that accuracy, and
    the signed gap (confidence - accuracy). Positive gap = overconfident.
    """
    c, y = _check(confidences, labels)
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    if strategy == "quantile":
        groups = _equal_frequency_groups(c, n_bins)
    elif strategy == "uniform":
        groups = _equal_width_groups(c, n_bins)
    else:
        raise ValueError("strategy must be 'quantile' or 'uniform'")

    rows = []
    for b, g in enumerate(groups):
        n = len(g)
        conf_mean = sum(c[i] for i in g) / n
        correct = sum(y[i] for i in g)
        acc = correct / n
        lo, hi = wilson_interval(correct, n)
        rows.append({
            "bin": b,
            "n": n,
            "conf_min": min(c[i] for i in g),
            "conf_max": max(c[i] for i in g),
            "conf_mean": conf_mean,
            "correct": correct,
            "accuracy": acc,
            "acc_ci_lo": lo,
            "acc_ci_hi": hi,
            "gap": conf_mean - acc,
        })
    return rows


def expected_calibration_error(
    confidences: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: str = "quantile",
) -> float:
    """Sample-weighted mean |confidence - accuracy| across bins. 0 is perfect."""
    rows = reliability_table(confidences, labels, n_bins=n_bins, strategy=strategy)
    total = sum(r["n"] for r in rows)
    return sum(r["n"] * abs(r["gap"]) for r in rows) / total


def maximum_calibration_error(
    confidences: Sequence[float],
    labels: Sequence[int],
    n_bins: int = 10,
    strategy: str = "quantile",
) -> float:
    """Largest single-bin |confidence - accuracy|."""
    rows = reliability_table(confidences, labels, n_bins=n_bins, strategy=strategy)
    return max(abs(r["gap"]) for r in rows)


def roc_auc(confidences: Sequence[float], labels: Sequence[int]) -> Optional[float]:
    """
    Rank-based AUC with tie correction (Mann-Whitney U).

    Reported next to ECE so ranking quality and calibration quality are visible
    side by side; a calibrator changes the second without touching the first.
    Returns None when one class is absent (AUC undefined).
    """
    c, y = _check(confidences, labels)
    n_pos = sum(y)
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    order = sorted(range(len(c)), key=lambda i: c[i])
    ranks = [0.0] * len(c)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and c[order[j + 1]] == c[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    sum_pos = sum(ranks[i] for i in range(len(y)) if y[i] == 1)
    return (sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


class IsotonicCalibrator:
    """
    Monotone (pool-adjacent-violators) calibration map.

    Fits a non-decreasing step function from raw confidence to observed
    frequency, then applies it by linear interpolation. Monotone means the
    ranking is preserved exactly: isotonic can only change what a score *means*,
    never which of two mappings scores higher.

    Serialises to a plain (x, y) point list, so applying it needs no library:
        y = interpolate(x_points, y_points, raw)
    """

    def __init__(self, x_points: Optional[Sequence[float]] = None, y_points: Optional[Sequence[float]] = None):
        self.x_points: List[float] = list(x_points or [])
        self.y_points: List[float] = list(y_points or [])

    @property
    def fitted(self) -> bool:
        return len(self.x_points) > 0

    def fit(self, confidences: Sequence[float], labels: Sequence[int]) -> "IsotonicCalibrator":
        c, y = _check(confidences, labels)
        # Merge duplicate x values into a single weighted point.
        agg: Dict[float, List[float]] = {}
        for ci, yi in zip(c, y):
            slot = agg.setdefault(ci, [0.0, 0.0])
            slot[0] += yi
            slot[1] += 1.0
        xs = sorted(agg)
        vals = [agg[x][0] / agg[x][1] for x in xs]
        wts = [agg[x][1] for x in xs]

        # Pool adjacent violators.
        stack_v: List[float] = []
        stack_w: List[float] = []
        stack_n: List[int] = []
        for v, w in zip(vals, wts):
            stack_v.append(v)
            stack_w.append(w)
            stack_n.append(1)
            while len(stack_v) > 1 and stack_v[-2] > stack_v[-1]:
                v2 = stack_v.pop(); w2 = stack_w.pop(); n2 = stack_n.pop()
                v1 = stack_v.pop(); w1 = stack_w.pop(); n1 = stack_n.pop()
                stack_v.append((v1 * w1 + v2 * w2) / (w1 + w2))
                stack_w.append(w1 + w2)
                stack_n.append(n1 + n2)
        fitted: List[float] = []
        for v, n in zip(stack_v, stack_n):
            fitted.extend([v] * n)

        self.x_points = xs
        self.y_points = fitted
        return self

    def predict_one(self, x: float) -> float:
        if not self.fitted:
            raise RuntimeError("calibrator is not fitted")
        xs, ys = self.x_points, self.y_points
        if len(xs) == 1:
            return ys[0]
        if x <= xs[0]:
            return ys[0]
        if x >= xs[-1]:
            return ys[-1]
        lo, hi = 0, len(xs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if xs[mid] <= x:
                lo = mid
            else:
                hi = mid
        span = xs[hi] - xs[lo]
        if span == 0:
            return ys[lo]
        t = (x - xs[lo]) / span
        return ys[lo] + t * (ys[hi] - ys[lo])

    def predict(self, confidences: Iterable[float]) -> List[float]:
        return [self.predict_one(float(x)) for x in confidences]

    def to_dict(self) -> Dict[str, List[float]]:
        return {"kind": "isotonic", "x": list(self.x_points), "y": list(self.y_points)}

    @classmethod
    def from_dict(cls, d: Dict) -> "IsotonicCalibrator":
        if d.get("kind") != "isotonic":
            raise ValueError("not an isotonic calibrator payload: %r" % (d.get("kind"),))
        return cls(d["x"], d["y"])


class PlattCalibrator:
    """
    Logistic (Platt) calibration: p = sigmoid(a * x + b), fitted by Newton steps
    on the log-loss. Two parameters, so it needs far less data than isotonic but
    can only apply a sigmoid-shaped correction.
    """

    def __init__(self, a: float = 1.0, b: float = 0.0):
        self.a = a
        self.b = b
        self._fitted = False

    @property
    def fitted(self) -> bool:
        return self._fitted

    @staticmethod
    def _sigmoid(z: float) -> float:
        if z >= 0:
            return 1.0 / (1.0 + math.exp(-z))
        e = math.exp(z)
        return e / (1.0 + e)

    def fit(self, confidences: Sequence[float], labels: Sequence[int], iters: int = 100) -> "PlattCalibrator":
        c, y = _check(confidences, labels)
        # Platt's prior correction keeps the fit finite when a class is absent
        # or the score separates the classes perfectly.
        n_pos = sum(y)
        n_neg = len(y) - n_pos
        hi = (n_pos + 1.0) / (n_pos + 2.0)
        lo = 1.0 / (n_neg + 2.0)
        t = [hi if yi == 1 else lo for yi in y]
        a, b = 0.0, 0.0
        for _ in range(iters):
            g_a = g_b = h_aa = h_ab = h_bb = 0.0
            for xi, ti in zip(c, t):
                p = self._sigmoid(a * xi + b)
                d = p - ti
                w = max(p * (1 - p), 1e-12)
                g_a += d * xi
                g_b += d
                h_aa += w * xi * xi
                h_ab += w * xi
                h_bb += w
            h_aa += 1e-9
            h_bb += 1e-9
            det = h_aa * h_bb - h_ab * h_ab
            if abs(det) < 1e-15:
                break
            da = (g_a * h_bb - g_b * h_ab) / det
            db = (g_b * h_aa - g_a * h_ab) / det
            a -= da
            b -= db
            if abs(da) < 1e-10 and abs(db) < 1e-10:
                break
        self.a, self.b = a, b
        self._fitted = True
        return self

    def predict_one(self, x: float) -> float:
        if not self._fitted:
            raise RuntimeError("calibrator is not fitted")
        return self._sigmoid(self.a * float(x) + self.b)

    def predict(self, confidences: Iterable[float]) -> List[float]:
        return [self.predict_one(float(x)) for x in confidences]

    def to_dict(self) -> Dict[str, float]:
        return {"kind": "platt", "a": self.a, "b": self.b}

    @classmethod
    def from_dict(cls, d: Dict) -> "PlattCalibrator":
        if d.get("kind") != "platt":
            raise ValueError("not a platt calibrator payload: %r" % (d.get("kind"),))
        obj = cls(float(d["a"]), float(d["b"]))
        obj._fitted = True
        return obj
