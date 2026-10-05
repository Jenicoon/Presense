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
