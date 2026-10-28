"""Recover complete selected evidence from exact saved action IDs, never guessed ranges."""

from copy import deepcopy

from .report_schema import ReviewRequest
from .session_analyzer import metric


def complete_report_evidence(report, segments):
    report = deepcopy(report)
    request = ReviewRequest(
        sessionId=report["sessionId"],
        durationMs=max((s["endMs"] for s in segments), default=1),
        segments=segments,
    )
    raw = {s.segmentId: s for s in request.segments}
    for finding in report.get("priorities", []):
        if not finding.get("modality") or not finding.get("metric"):
            continue
        ids = finding.get("selectedSegmentIds")
        if not ids:
            action = next(
                (
                    a
                    for a in reversed(report.get("agentRun", {}).get("actions", []))
                    if a.get("action") == "analyze_segment"
                    and a.get("candidateId") == finding["id"]
                    and a.get("segmentIds")
                ),
                None,
            )
            ids = (
                action["segmentIds"]
                if action
                else [o["segmentId"] for o in finding.get("observations", [])]
            )
        selected = [
            raw[i]
            for i in dict.fromkeys(ids)
            if i in raw
            and metric(raw[i], finding["modality"], finding["metric"]) is not None
        ]
        independent = []
        for row in sorted(selected, key=lambda s: (s.endMs, s.startMs)):
            if not independent or row.startMs >= independent[-1].endMs:
                independent.append(row)
        finding["observations"] = [
            {
                "segmentId": s.segmentId,
                "startMs": s.startMs,
                "endMs": s.endMs,
                "value": metric(s, finding["modality"], finding["metric"]),
                "stressScore": s.stressScore,
                "conceptValues": s.concepts
                if s.quality.audioValid and s.quality.faceDetected
                else {},
            }
            for s in independent
        ]
        finding["observationEvidenceComplete"] = len(independent) == finding.get(
            "independentObservations", len(independent)
        )
        finding["verifiedObservationCount"] = len(independent)
        if ids:
            finding["selectedSegmentIds"] = list(dict.fromkeys(ids))
    return report


def complete_document_evidence(doc):
    if doc is None:
        return None
    doc = deepcopy(doc)
    snapshot = doc["snapshot"]
    snapshot["report"] = complete_report_evidence(
        snapshot["report"], snapshot["request"]["segments"]
    )
    return doc


def observation_video_cards(doc, finding, ko):
    return [
        {
            "type": "video_segment",
            "sessionId": doc["state"]["sessionId"],
            "findingId": finding["id"],
            "startMs": o["startMs"],
            "endMs": o["endMs"],
            "label": "관측 구간" if ko else "Observed interval",
        }
        for o in finding.get("observations", [])
    ]


def attach_observation_videos(response, doc, ko):
    """All supporting intervals travel together, even if the LLM picked one example."""
    response = deepcopy(response)
    finding_id = response["conversationState"].get("selectedFindingId")
    finding = next(
        (
            f
            for f in doc["snapshot"]["report"].get("priorities", [])
            if f["id"] == finding_id
        ),
        None,
    )
    if not finding or not finding.get("observations"):
        return response
    # Do not attach a current-session evidence group to a previous/retry comparison.
    components = response["components"]
    if any(c["type"] == "comparison" for c in components):
        return response
    has_finding_fact = f"finding.{finding_id}" in response.get("generation", {}).get(
        "evidenceIds", []
    )
    if not has_finding_fact and not any(
        c["type"] == "video_segment" and c["sessionId"] == doc["state"]["sessionId"]
        for c in components
    ):
        return response
    group = observation_video_cards(doc, finding, ko)
    spans = {(c["sessionId"], c["startMs"], c["endMs"]) for c in group}
    remaining = [
        c
        for c in components
        if not (
            c["type"] == "video_segment"
            and (
                c.get("findingId") == finding_id
                or (c["sessionId"], c["startMs"], c["endMs"]) in spans
            )
        )
    ]
    if finding.get("observationEvidenceComplete") is False:
        remaining.insert(
            0,
            {
                "type": "insufficient_data",
                "label": "기록된 관측 수와 확인 가능한 구간 수가 다릅니다. 확인 가능한 근거만 표시합니다."
                if ko
                else "The recorded count and available intervals differ. Only verifiable evidence is shown.",
            },
        )
    response["components"] = group + remaining
    return response
