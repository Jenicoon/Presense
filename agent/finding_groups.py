"""Conservative grouping of measured changes; never a delivery-quality cutoff."""
from math import isfinite

METRIC_FLOORS = {"f0_mean": 100, "f0_std": 20, "egemap_f0_semitone": 10,
                 "egemap_jitter": .01, "egemap_shimmer_db": .2, "egemap_hnr_db": 1}


def repeated_group_reason(rows, reference, metric):
    """All members must be separate, meaningfully shifted and similar in direction/size.

    Reuse the existing 10% review threshold. The within-group spread must be
    smaller than every member's distance to the reference, so a near-reference
    window cannot serve as repetition of a distant one. This is a display and
    evidence-consistency rule, not a statistical significance or medical test.
    """
    if not isinstance(reference, (int, float)) or not isfinite(reference):
        return "missing_reference"
    if len(rows) < 2:
        return "insufficient_independent_observations"
    ordered = sorted(rows, key=lambda row: (row["startMs"], row["endMs"]))
    if any(a["endMs"] > b["startMs"] for a, b in zip(ordered, ordered[1:])):
        return "overlapping_observations"
    values = [row["value"] for row in rows]
    if any(not isinstance(value, (int, float)) or not isfinite(value) for value in values):
        return "missing_measurement"
    changes = [value - reference for value in values]
    threshold = max(abs(reference), METRIC_FLOORS.get(metric, .15)) * .1
    if any(abs(change) < threshold for change in changes):
        return "includes_reference_like_observation"
    if not (all(change > 0 for change in changes) or all(change < 0 for change in changes)):
        return "mixed_directions"
    if max(values) - min(values) >= min(abs(change) for change in changes):
        return "dissimilar_changes"
    return None


def finding_kind(rows, reference, metric, earlier_values):
    """A repeated shift OR a single prominent measured interval can merit review.

    A single interval needs at least three independent earlier measurements.
    Its deviation must exceed both the existing review floor and twice the
    earlier observed range. This conservative product heuristic accounts for
    ordinary variation; it is not a clinical or statistical significance test.
    Model stress scores do not participate in this decision.
    """
    if repeated_group_reason(rows, reference, metric) is None:
        return "repeated"
    if len(rows) != 1 or len(earlier_values) < 3:
        return None
    if not isinstance(reference, (int, float)) or not isfinite(reference):
        return None
    value = rows[0].get("value")
    if (not isinstance(value, (int, float)) or not isfinite(value)
            or any(not isinstance(v, (int, float)) or not isfinite(v) for v in earlier_values)):
        return None
    deviation = abs(value - reference)
    required = max(max(abs(reference), METRIC_FLOORS.get(metric, .15)) * .1,
                   2 * (max(earlier_values) - min(earlier_values)))
    return "distinct" if deviation > required else None
