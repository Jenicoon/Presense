"""Summarize model measurements without selecting noteworthy stress intervals.

The measurement catalogue supplies names and research vocabulary only. Every
valid feature remains available across the full observed session; the Agent
chooses both the feature and the intervals worth inspecting.
"""
from collections import defaultdict
from math import isfinite
from statistics import median

from .report_schema import ReviewRequest, SegmentAnalysis

MEASUREMENT_INFO = {
    ("audio", "f0_mean"): ("pitch_change", "평균 목소리 높이 / Mean voice pitch",
                            "fundamental frequency F0 pitch public speaking"),
    ("audio", "f0_std"): ("pitch_variability", "음높이 변동 / Pitch variability",
                           "fundamental frequency variability intonation public speaking"),
    ("video", "lip_tension"): ("lip_tension", "입술 간격 추정치 / Lip aperture estimate",
                                "lip aperture mouth movement speaking"),
    ("video", "brow_tension"): ("brow_tension", "눈썹 움직임 추정치 / Brow movement estimate",
                                 "brow lowerer facial movement public speaking"),
    ("video", "eye_contact_score"): ("gaze", "시선 안정도 추정치 / Gaze stability estimate",
                                      "gaze stability public speaking"),
}
RESEARCHABLE_IDS = frozenset(info[0] for info in MEASUREMENT_INFO.values())


def metric(segment: SegmentAnalysis, modality: str, key: str) -> float | None:
    """Return a physically usable model output, without judging its desirability."""
    if modality == "audio":
        valid, values = segment.quality.audioValid, segment.audioFeatures
    elif modality == "video":
        valid, values = segment.quality.faceDetected, segment.videoFeatures
    elif modality == "concept":
        valid, values = segment.quality.audioValid and segment.quality.faceDetected, segment.concepts
    else:
        return None
    value = values.get(key)
    if not valid or isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    if key == "f0_mean" and value <= 0:
        return None
    if key == "f0_std" and value < 0:
        return None
    return float(value)


def intervals(segments):
    """Disjoint intervals with the set of overlapping observations."""
    events = defaultdict(list)
    for index, segment in enumerate(segments):
        events[segment.startMs].append((index, True))
        events[segment.endMs].append((index, False))
    active = set()
    previous = None
    for point in sorted(events):
        if previous is not None and point > previous and active:
            yield previous, point, tuple(sorted(active))
        for index, add in events[point]:
            if add:
                active.add(index)
            else:
                active.discard(index)
        previous = point


def _independent_count(rows: list[SegmentAnalysis]) -> int:
    count, last_end = 0, -1
    for row in sorted(rows, key=lambda item: (item.endMs, item.startMs)):
        if row.startMs >= last_end:
            count += 1
            last_end = row.endMs
    return count


def _ranges(rows: list[SegmentAnalysis]) -> list[dict]:
    output = []
    for row in sorted(rows, key=lambda item: (item.startMs, item.endMs)):
        if output and row.startMs <= output[-1]["endMs"]:
            output[-1]["endMs"] = max(output[-1]["endMs"], row.endMs)
        else:
            output.append({"startMs": row.startMs, "endMs": row.endMs})
    return output


def _feature_keys(segments: list[SegmentAnalysis]) -> list[tuple[str, str]]:
    keys = set()
    for segment in segments:
        for modality, values in (("audio", segment.audioFeatures),
                                 ("video", segment.videoFeatures),
                                 ("concept", segment.concepts)):
            for key in values:
                if metric(segment, modality, key) is not None:
                    keys.add((modality, key))
    return sorted(keys)


def analyze_session(request: ReviewRequest):
    segments = sorted(request.segments, key=lambda s: (s.startMs, s.endMs, s.segmentId))
    usable = [s for s in segments if s.quality.audioValid or s.quality.faceDetected]
    cells = []
    total = weighted = 0
    for start, end, active in intervals(usable):
        score = sum(usable[i].stressScore for i in active) / len(active)
        length = end - start
        total += length
        weighted += score * length
        cells.append({"startMs": start, "endMs": end, "stressScore": round(score, 4)})
    summary = {
        "durationMs": request.durationMs, "observedMs": total,
        "coverage": round(total / request.durationMs, 4),
        "averageStress": round(weighted / total, 4) if total else None,
        "peakStress": max((s.stressScore for s in usable), default=None),
        "timeline": cells,
        "segmentCount": len(segments), "usableSegmentCount": len(usable),
    }

    candidates = []
    for modality, key in _feature_keys(usable):
        identity, label, query = MEASUREMENT_INFO.get(
            (modality, key), (f"{modality}:{key}", f"{modality} · {key}",
                              f"{key.replace('_', ' ')} public speaking measurement"))
        series = [{"segmentId": s.segmentId, "startMs": s.startMs, "endMs": s.endMs,
                   "value": metric(s, modality, key), "stressScore": s.stressScore}
                  for s in usable]
        measured = [s for s in usable if metric(s, modality, key) is not None]
        confidences = [s.predictionConfidence for s in measured
                       if s.predictionConfidence is not None]
        examples = sorted(measured, key=lambda s: (-s.stressScore, s.startMs))[:3]
        candidates.append({
            "id": identity, "label": label, "modality": modality, "metric": key,
            "referenceValue": None, "selectionBasis": "all_valid_model_measurements",
            "durationMs": sum(end-start for start, end, _ in intervals(usable)),
            "ranges": _ranges(usable),
            "query": query,
            "predictionConfidence": round(median(confidences), 4) if confidences else None,
            "measurementQuality": round(len(measured) / len(usable), 4),
            "independentObservations": _independent_count(measured),
            "observations": [{"segmentId": s.segmentId, "startMs": s.startMs,
                              "endMs": s.endMs, "value": metric(s, modality, key),
                              "stressScore": s.stressScore,
                              "conceptValues": s.concepts if s.quality.audioValid and s.quality.faceDetected else {}}
                             for s in examples],
            "measurementSeries": series,
        })
    return summary, candidates


def describe_observations(request: ReviewRequest, summary: dict) -> dict:
    """Factual model outputs shown even when no coaching finding passes review."""
    usable = [segment for segment in request.segments
              if segment.quality.audioValid or segment.quality.faceDetected]
    peak = max(usable, key=lambda segment: segment.stressScore, default=None)
    concepts = []
    names = sorted({name for segment in usable
                    if segment.quality.audioValid and segment.quality.faceDetected
                    for name in segment.concepts})
    for name in names:
        values = [metric(segment, "concept", name) for segment in usable]
        values = [value for value in values if value is not None]
        if values:
            concepts.append({"name": name, "meanValue": round(sum(values) / len(values), 4),
                             "observations": len(values)})
    concepts.sort(key=lambda row: (-row["meanValue"], row["name"]))

    features = []
    for (modality, key), (identity, label, _) in MEASUREMENT_INFO.items():
        values = [metric(segment, modality, key) for segment in usable]
        values = [value for value in values if value is not None]
        if values:
            features.append({"id": identity, "label": label,
                             "meanValue": round(sum(values) / len(values), 4),
                             "minValue": round(min(values), 4),
                             "maxValue": round(max(values), 4),
                             "observations": len(values),
                             "unit": "Hz" if key in {"f0_mean", "f0_std"} else ""})

    patterns = []
    if peak:
        for (modality, key), (identity, label, _) in MEASUREMENT_INFO.items():
            focus_value = metric(peak, modality, key)
            others = [metric(segment, modality, key) for segment in usable
                      if segment.segmentId != peak.segmentId]
            others = [value for value in others if value is not None]
            if focus_value is None or not others:
                continue
            reference = median(others)
            delta = focus_value - reference
            if abs(delta) < 1e-6:
                continue
            scale = max(abs(reference), {"f0_mean": 100, "f0_std": 20}.get(key, .15))
            if abs(delta) / scale < .1:
                continue
            patterns.append({"id": identity, "label": label,
                             "startMs": peak.startMs, "endMs": peak.endMs,
                             "value": round(focus_value, 4),
                             "comparisonValue": round(reference, 4),
                             "difference": round(delta, 4),
                             "unit": "Hz" if key in {"f0_mean", "f0_std"} else "",
                             "comparisonCount": len(others),
                             "relativeChange": abs(delta) / scale})
    patterns.sort(key=lambda row: (-row["relativeChange"], row["id"]))
    for pattern in patterns:
        pattern.pop("relativeChange")

    phase_summaries = []
    for index in range(3):
        start, end = request.durationMs * index // 3, request.durationMs * (index + 1) // 3
        observed = weighted = 0
        for cell in summary["timeline"]:
            overlap = max(0, min(end, cell["endMs"]) - max(start, cell["startMs"]))
            observed += overlap
            weighted += overlap * cell["stressScore"]
        phase_summaries.append({"startMs": start, "endMs": end,
                                "observedMs": observed,
                                "averageStressScore": round(weighted / observed, 4) if observed else None})

    peak_concepts = []
    if peak and peak.quality.audioValid and peak.quality.faceDetected:
        for name in peak.concepts:
            value = metric(peak, "concept", name)
            other_values = [metric(segment, "concept", name) for segment in usable
                            if segment.segmentId != peak.segmentId]
            other_values = [other for other in other_values if other is not None]
            if value is not None and other_values:
                reference = median(other_values)
                if abs(value - reference) >= .05:
                    peak_concepts.append({"name": name, "value": round(value, 4),
                                          "comparisonValue": round(reference, 4),
                                          "difference": round(value - reference, 4)})
    peak_concepts.sort(key=lambda row: (-abs(row["difference"]), row["name"]))
    return {
        "observedMs": summary["observedMs"], "coverage": summary["coverage"],
        "averageStressScore": summary["averageStress"],
        "peakSegment": ({"startMs": peak.startMs, "endMs": peak.endMs,
                         "stressScore": peak.stressScore, "segmentId": peak.segmentId}
                        if peak else None),
        "stressTimeline": summary["timeline"],
        "concepts": concepts, "features": features,
        "patterns": patterns[:2], "modelWindowCount": len(usable),
        "phaseSummaries": phase_summaries, "peakConcepts": peak_concepts[:2],
    }
