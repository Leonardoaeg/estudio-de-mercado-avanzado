"""TrendEngine — section 24. Compares two snapshots' aggregated counts (per product,
keyword, subniche, hook, angle, format or offer) and reports an "Advertising Trend"
(more advertisers/ads mentioning X), explicitly never a "Sales Trend" — section 24 is
emphatic about that distinction, since we have no sales data at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TrendResult:
    dimension: str
    label: str
    baseline_count: int
    current_count: int
    variation_percentage: float | None  # None when baseline_count == 0 ("new" entrant)
    is_new: bool


def compare_counts(
    dimension: str,
    baseline_counts: dict[str, int],
    current_counts: dict[str, int],
    *,
    min_current_count: int = 2,
) -> list[TrendResult]:
    """`min_current_count` filters out one-off noise (a label appearing once isn't a trend)."""
    results: list[TrendResult] = []
    all_labels = set(baseline_counts) | set(current_counts)
    for label in all_labels:
        baseline = baseline_counts.get(label, 0)
        current = current_counts.get(label, 0)
        if current < min_current_count:
            continue
        if baseline == 0:
            results.append(TrendResult(dimension, label, 0, current, None, is_new=True))
        else:
            variation = round((current - baseline) / baseline * 100, 1)
            results.append(TrendResult(dimension, label, baseline, current, variation, is_new=False))

    # Rank: new entrants and biggest positive movers first.
    results.sort(key=lambda r: (not r.is_new, -(r.variation_percentage or 10_000)))
    return results


@dataclass
class SnapshotWindow:
    period_start: datetime
    period_end: datetime
    counts_by_dimension: dict[str, dict[str, int]]  # {"product": {"leggings": 9}, "hook": {...}, ...}


def build_trend_report(baseline: SnapshotWindow, current: SnapshotWindow) -> dict[str, list[TrendResult]]:
    report: dict[str, list[TrendResult]] = {}
    dimensions = set(baseline.counts_by_dimension) | set(current.counts_by_dimension)
    for dim in dimensions:
        report[dim] = compare_counts(
            dim,
            baseline.counts_by_dimension.get(dim, {}),
            current.counts_by_dimension.get(dim, {}),
        )
    return report
