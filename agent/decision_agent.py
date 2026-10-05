from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import median
from typing import Callable

from .report_schema import Evidence, ReviewRequest
from .session_analyzer import RESEARCHABLE_IDS, _independent_count, _ranges, metric


# 1. 설정값과 AgentState: 실행 한도와 분석 중 유지할 상태.

logger = logging.getLogger(__name__)
MAX_ACTIONS = 5
MAX_PAPER_SEARCHES = 2
MAX_DECISION_ATTEMPTS = 3
METRIC_DEFINITION_VERSION = "session-analysis-v4"


@dataclass
class AgentState:
    request: ReviewRequest
    summary: dict
    candidates: list[dict]
    prior: dict | None = None
    model_version: str = "unknown"
    findings: dict[str, list[dict]] = field(default_factory=dict)
    hits: dict[str, list[Evidence]] = field(default_factory=dict)
    actions: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    seen: set[tuple[str, str]] = field(default_factory=set)
    selected_ids: list[str] = field(default_factory=list)
    decision_errors: list[str] = field(default_factory=list)
    stop_reason: str = "action_limit"

    def candidate(self, identity: str) -> dict:
        return next(item for item in self.candidates if item["id"] == identity)


# 2. Luxia에게 보여줄 상태 만들기: 후보와 발표 구간을 읽기 쉬운 입력으로 정리.

def _candidate_view(item: dict) -> dict:
    series = item.get("measurementSeries", [])
    valid = [row["value"] for row in series if row["value"] is not None]
    valid_rows = [row for row in series if row["value"] is not None]
    examples = (series[:2] + series[-2:]
                + sorted(valid_rows, key=lambda row: row["value"])[:2]
                + sorted(valid_rows, key=lambda row: -row["value"])[:2]
                + sorted(series, key=lambda row: (-row["stressScore"], row["startMs"]))[:4])
    samples = sorted({row["segmentId"]: row for row in examples}.values(),
                     key=lambda row: (row["startMs"], row["segmentId"]))
    return {
        "candidateId": item["id"], "label": item["label"],
        "modality": item["modality"], "metric": item["metric"],
        "ranges": item["ranges"], "referenceValue": item["referenceValue"],
        "valueRange": [min(valid), max(valid)] if valid else None,
        "sampleWindows": samples,
        "predictionConfidence": item["predictionConfidence"],
        "measurementQuality": item["measurementQuality"],
        "independentObservations": item["independentObservations"],
        "relatedConcepts": sorted({name for observation in item["observations"]
                                    for name in observation["conceptValues"]}),
    }


def _session_window_view(request: ReviewRequest) -> list[dict]:
    """Bound the context size while exposing time and score without a cutoff."""
    rows = sorted(request.segments, key=lambda row: (row.startMs, row.segmentId))
    if len(rows) > 48:
        even = {round(index * (len(rows) - 1) / 31) for index in range(32)}
        score_extremes = sorted(range(len(rows)), key=lambda index: rows[index].stressScore)
        changes = sorted(range(1, len(rows)),
                         key=lambda index: abs(rows[index].stressScore - rows[index - 1].stressScore),
                         reverse=True)
        indices = even | set(score_extremes[:4]) | set(score_extremes[-4:]) | set(changes[:8])
        rows = [rows[index] for index in sorted(indices)]
    return [{"segmentId": row.segmentId, "startMs": row.startMs, "endMs": row.endMs,
             "stressScore": row.stressScore,
             "audioValid": row.quality.audioValid, "faceDetected": row.quality.faceDetected}
            for row in rows]


def _decision_view(state: AgentState, rag) -> dict:
    weak = _weak_measurement_context(state)
    review_ready = [item["id"] for item in state.candidates
                    if ("analyze_segment", item["id"]) in state.seen
                    and item["measurementQuality"] >= .8
                    and item["independentObservations"] >= 2
                    and any(hit.applicability == "direct" and item["id"] in hit.topics
                            for hit in state.hits.get(item["id"], []))]
    prior_goal = (state.prior or {}).get("focusGoal")
    prior_goal_id = prior_goal.get("candidateId") if isinstance(prior_goal, dict) else None
    pending_prior_goal = (prior_goal_id if prior_goal_id in {item["id"] for item in state.candidates}
                          and _has_comparison(state, prior_goal_id)
                          and ("compare_previous_session", prior_goal_id) not in state.seen else None)
    return {"remainingActions": MAX_ACTIONS - len(state.actions),
            "remainingPaperSearches": MAX_PAPER_SEARCHES - sum(a["action"] == "retrieve_papers" for a in state.actions),
            "summary": {key: value for key, value in state.summary.items() if key != "timeline"},
            "sessionWindows": _session_window_view(state.request),
            "candidates": [_candidate_view(item) for item in state.candidates],
            "priorGoal": {key: (state.prior or {}).get("focusGoal", {}).get(key)
                          for key in ("candidateId", "metric")}
            if isinstance((state.prior or {}).get("focusGoal"), dict) else None,
            "comparableCandidateIds": [item["id"] for item in state.candidates if _has_comparison(state, item["id"])],
            "paperEligibleCandidateIds": [item["id"] for item in state.candidates
                                          if _paper_eligible(state, item, rag)[0]],
            "conceptEligibleCandidateIds": [item["id"] for item in state.candidates
                                            if _concept_eligible(item)[0]
                                            and ("analyze_concept", item["id"]) not in state.seen
                                            and (weak is None or item["id"] in weak["sameIntervalAlternatives"])],
            "reviewReadyCandidateIds": review_ready,
            "finishEligibleCandidateIds": _finish_eligible_ids(state),
            "pendingPriorGoalComparisonId": pending_prior_goal,
            "paperSearchAvailable": rag is not None,
            "weakMeasurementContext": weak,
            "decisionErrors": state.decision_errors[-2:],
            "toolResults": state.actions}


# 3. 측정값과 이전 세션 비교: 기준값, 관측 횟수, 비교 가능성 계산.

def _prior_candidate(prior: dict | None, identity: str, model_version: str, scene: str | None) -> dict | None:
    if not prior or model_version == "unknown" or prior.get("modelVersion") != model_version:
        return None
    if prior.get("metricDefinitionVersion") != METRIC_DEFINITION_VERSION:
        return None
    if not scene or scene != prior.get("sceneLabel"):
        return None
    return next((item for item in prior.get("candidates", [])
                 if isinstance(item, dict) and item.get("candidateId") == identity
                 and item.get("observationCount", 0) >= 2
                 and item.get("measurementQuality", 0) >= .8
                 and isinstance(item.get("observedValue"), (int, float))), None)


def _has_comparison(state: AgentState, identity: str) -> bool:
    current = state.candidate(identity)
    _, count, quality = _session_measurement(state.request, current)
    previous_duration = (state.prior or {}).get("durationMs")
    return (count >= 2 and quality >= .8
            and isinstance(previous_duration, (int, float))
            and .5 <= state.request.durationMs / max(previous_duration, 1) <= 2
            and (previous := _prior_candidate(state.prior, identity, state.model_version,
                                               state.request.sceneLabel)) is not None
            and previous.get("metric") == current["metric"])


def _observation_value(item: dict) -> float | None:
    values = [row["value"] for row in item["observations"] if isinstance(row.get("value"), (int, float))]
    return round(median(values), 4) if values else None


def _session_measurement(request: ReviewRequest, item: dict) -> tuple[float | None, int, float]:
    """Use the same whole-session definition before and after interval review."""
    usable = [row for row in request.segments if row.quality.audioValid or row.quality.faceDetected]
    measured = [row for row in usable if metric(row, item["modality"], item["metric"]) is not None]
    values = [metric(row, item["modality"], item["metric"]) for row in measured]
    return (round(median(values), 4) if values else None,
            _independent_count(measured), round(len(measured) / len(usable), 4) if usable else 0)


def _coherent_shift_count(values: list[float], reference: float | None) -> int:
    """Count observations closer to another shifted value than to baseline.

    This uses the presentation's own measurements. Two total observations do
    not establish repetition when one resembles baseline and only one changes.
    """
    if reference is None:
        return 0
    count = 0
    for index, value in enumerate(values):
        peers = [other for peer_index, other in enumerate(values)
                 if peer_index != index and (other - reference) * (value - reference) > 0]
        if peers and min(abs(value - other) for other in peers) < abs(value - reference):
            count += 1
    return count


# 4. 도구 실행: Luxia가 고른 구간, concept, 이전 세션, 논문을 조사.

def _segment_result(state: AgentState, item: dict, segment_ids: list[str] | None = None) -> dict:
    if segment_ids is not None:
        selected = [row for row in state.request.segments if row.segmentId in segment_ids]
        valid = [row for row in selected if metric(row, item["modality"], item["metric"]) is not None]
        earlier = [metric(row, item["modality"], item["metric"])
                   for row in state.request.segments
                   if row.endMs <= min(part.startMs for part in selected)
                   and metric(row, item["modality"], item["metric"]) is not None]
        item["ranges"] = _ranges(selected)
        item["durationMs"] = sum(span["endMs"] - span["startMs"] for span in item["ranges"])
        item["referenceValue"] = median(earlier) if len(earlier) >= 2 else None
        item["measurementQuality"] = round(len(valid) / len(selected), 4)
        item["independentObservations"] = _independent_count(valid)
        confidence = [row.predictionConfidence for row in valid if row.predictionConfidence is not None]
        item["predictionConfidence"] = round(median(confidence), 4) if confidence else None
        if item["id"] in {"pitch_change", "pitch_variability"}:
            item["coherentShiftCount"] = _coherent_shift_count(
                [metric(row, item["modality"], item["metric"]) for row in valid],
                item["referenceValue"])
        item["observations"] = [{"segmentId": row.segmentId, "startMs": row.startMs,
                                 "endMs": row.endMs, "value": metric(row, item["modality"], item["metric"]),
                                 "stressScore": row.stressScore,
                                 "conceptValues": row.concepts if row.quality.audioValid and row.quality.faceDetected else {}}
                                for row in valid[:3]]
    ranges = item["ranges"]
    observations = [row for row in item["observations"]
                    if any(row["startMs"] < span["endMs"] and row["endMs"] > span["startMs"]
                           for span in ranges)]
    return {"candidateId": item["id"], "ranges": ranges, "metric": item["metric"],
            "observedValue": _observation_value(item), "referenceValue": item.get("referenceValue"),
            "supportingSegmentIds": [row["segmentId"] for row in observations],
            "independentObservations": item["independentObservations"],
            "measurementQuality": item["measurementQuality"],
            **({"coherentShiftCount": item["coherentShiftCount"]}
               if "coherentShiftCount" in item else {})}


def _concept_result(state: AgentState, item: dict) -> dict:
    rows = item["observations"]
    names = sorted({key for row in rows for key in row["conceptValues"]})
    baseline = {}
    last_end = -1
    first_review_start = min((row["startMs"] for row in rows), default=0)
    for segment in sorted(state.request.segments, key=lambda s: s.startMs):
        if (segment.endMs <= first_review_start and segment.startMs >= last_end
                and segment.quality.audioValid and segment.quality.faceDetected
                and segment.concepts):
            for name, value in segment.concepts.items():
                baseline.setdefault(name, []).append(value)
            last_end = segment.endMs
    return {"candidateId": item["id"], "relationship": "co_observed_not_causal",
            "conceptObservationCount": sum(bool(row["conceptValues"]) for row in rows),
            "concepts": [{"name": name, "meanPrediction": round(sum(row["conceptValues"][name]
                           for row in rows if name in row["conceptValues"]) /
                           sum(name in row["conceptValues"] for row in rows), 4),
                          "referencePrediction": round(median(baseline[name]), 4)
                          if len(baseline.get(name, [])) >= 3 else None} for name in names]}


def _comparison_result(state: AgentState, item: dict) -> dict:
    prior = _prior_candidate(state.prior, item["id"], state.model_version, state.request.sceneLabel)
    current, _, _ = _session_measurement(state.request, item)
    previous = prior.get("observedValue") if prior else None
    if previous is None or current is None:
        return {"candidateId": item["id"], "comparable": False}
    return {"candidateId": item["id"], "comparable": True,
            "previousSessionId": state.prior.get("sessionId"),
            "previousValue": previous, "currentValue": current,
            "difference": round(current - previous, 4),
            "interpretation": "metric_difference_only_not_coaching_improvement"}


def _paper_result(item: dict, rag, claim_kind: str) -> tuple[dict, list[Evidence]]:
    claim = (f"A presentation rehearsal exercise targeting {item['metric']} may improve delivery"
             if claim_kind == "practice" else
             f"The observed {item['metric']} change may be relevant when reviewing this speaking interval")
    query = (f"{item['query']} {claim} public speaking adults"
             + (" feedback rehearsal intervention" if claim_kind == "practice" else ""))
    try:
        retriever = getattr(rag, "retrieve_issue_evidence", None)
        raw = retriever(item["id"], query, k=5) if retriever else rag.retrieve_evidence(query, k=5)
        from .report_agent import _eligible_evidence  # reuse curated scope guard
        hits = [hit for entry in raw if _eligible_evidence(item["id"], hit := Evidence.model_validate(entry))]
    except Exception as error:
        logger.warning("Agent paper tool failed (%s)", type(error).__name__)
        hits = []
    direct = [hit for hit in hits if hit.applicability == "direct" and item["id"] in hit.topics]
    practice = [hit for hit in direct if hit.evidenceRole == "practice_specific"]
    support = "direct" if (practice if claim_kind == "practice" else direct) else "partial" if hits else "unsupported"
    return {"candidateId": item["id"], "claimKind": claim_kind, "claim": claim,
            "supportsClaim": "partial" if hits else "false", "support": support,
            "evidenceIds": [hit.id for hit in hits],
            "evidenceScope": [hit.scope for hit in hits if hit.scope],
            "sources": [{"id": hit.id, "source": hit.source, "page": hit.page,
                         "scope": hit.scope, "limitation": hit.scope}
                        for hit in hits]}, hits


# 5. 서버 검증 규칙: 불충분하거나 허용되지 않은 행동을 차단.

def _paper_eligible(state: AgentState, item: dict, rag) -> tuple[bool, str]:
    identity = item["id"]
    if identity not in RESEARCHABLE_IDS:
        return False, "no_indexed_research_topic"
    if rag is None or sum(row["action"] == "retrieve_papers" for row in state.actions) >= MAX_PAPER_SEARCHES:
        return False, "paper_search_unavailable_or_exhausted"
    if ("retrieve_papers", identity) in state.seen:
        return False, "paper_search_already_done"
    if ("analyze_segment", identity) not in state.seen:
        return False, "candidate_measurement_not_checked"
    if item["measurementQuality"] < .8:
        return False, "candidate_quality_below_0_8"
    if item["independentObservations"] < 2:
        return False, "candidate_not_repeated"
    if item["id"] in {"pitch_change", "pitch_variability"} and item.get("coherentShiftCount", 2) < 2:
        return False, "candidate_change_not_repeated"
    observed_values = [row["value"] for row in item["observations"]
                       if isinstance(row.get("value"), (int, float))]
    if (observed_values and len(set(observed_values)) == 1
            and (item["referenceValue"] is None or item["referenceValue"] == observed_values[0])):
        return False, "candidate_has_no_observed_change"
    return True, "eligible"


def _concept_eligible(item: dict) -> tuple[bool, str]:
    if item["measurementQuality"] < .8:
        return False, "candidate_quality_below_0_8"
    if item["independentObservations"] < 2:
        return False, "candidate_not_repeated"
    valid_concepts = [row for row in item["observations"] if row["conceptValues"]]
    if len(valid_concepts) < 2:
        return False, "concept_observation_not_repeated"
    return True, "eligible"


def _weak_measurement_context(state: AgentState) -> dict | None:
    """Show whether another feature has independent data in a weak interval."""
    if not state.actions or state.actions[-1]["action"] != "analyze_segment":
        return None
    last = state.actions[-1]
    result = last["result"]
    if (result["measurementQuality"] >= .8 and result["independentObservations"] >= 2
            and result.get("coherentShiftCount", 2) >= 2):
        return None
    selected_ids = set(last.get("segmentIds", result["supportingSegmentIds"]))
    selected = [row for row in state.request.segments if row.segmentId in selected_ids]
    if not selected:
        return None
    first_start = min(row.startMs for row in selected)
    alternatives = []
    for item in state.candidates:
        if item["id"] == last["candidateId"] or ("analyze_segment", item["id"]) in state.seen:
            continue
        observed = [row for row in selected if metric(row, item["modality"], item["metric"]) is not None]
        if len(observed) / len(selected) < .8 or _independent_count(observed) < 2:
            continue
        earlier = [metric(row, item["modality"], item["metric"])
                   for row in state.request.segments if row.endMs <= first_start
                   and metric(row, item["modality"], item["metric"]) is not None]
        values = [metric(row, item["modality"], item["metric"]) for row in observed]
        if len(earlier) >= 2 and _coherent_shift_count(values, median(earlier)) >= 2:
            alternatives.append(item["id"])
    return {"reviewSegmentIds": sorted(selected_ids),
            "sameIntervalAlternatives": alternatives}


def _finish_eligible_ids(state: AgentState) -> list[str]:
    """Only measurements the agent actually checked and the finish validator accepts."""
    selected = []
    for action in state.actions:
        if action["action"] != "analyze_segment":
            continue
        identity = action["candidateId"]
        item = state.candidate(identity)
        if (identity not in selected and item["measurementQuality"] >= .8
                and item["independentObservations"] >= 2
                and (identity not in {"pitch_change", "pitch_variability"}
                     or item.get("coherentShiftCount", 2) >= 2)):
            selected.append(identity)
    return selected


def _safe_next_action(state: AgentState, rag) -> dict:
    """Preserve checked measurements without inventing research-backed advice."""
    return {"action": "finish", "priorityCandidateIds": _finish_eligible_ids(state)[:3]}


def _validate_action(raw: dict, state: AgentState, rag) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Decision must be an object")
    action = raw.get("action")
    ids = [item["id"] for item in state.candidates]
    if action == "finish":
        selected = raw.get("priorityCandidateIds")
        if (not isinstance(selected, list) or len(selected) > 3
                or len(selected) != len(set(selected)) or any(i not in ids for i in selected)):
            raise ValueError("Finish must select observed candidate IDs only")
        for identity in selected:
            item = state.candidate(identity)
            if not ({("analyze_segment", identity), ("compare_previous_session", identity)} & state.seen):
                raise ValueError("candidate_measurement_not_checked")
            if item["measurementQuality"] < .8:
                raise ValueError("candidate_quality_below_0_8")
            if item["independentObservations"] < 2:
                raise ValueError("candidate_not_repeated")
            if (identity in {"pitch_change", "pitch_variability"}
                    and item.get("coherentShiftCount", 2) < 2):
                raise ValueError("candidate_change_not_repeated")
        return {"action": action, "priorityCandidateIds": selected}
    if action not in {"analyze_segment", "analyze_concept", "compare_previous_session", "retrieve_papers"}:
        raise ValueError("Unsupported tool")
    identity = raw.get("candidateId")
    if identity not in ids or (action, identity) in state.seen:
        raise ValueError("Unknown or repeated candidate action")
    item = state.candidate(identity)
    if action == "analyze_segment" and "segmentIds" in raw:
        selected = raw["segmentIds"]
        valid_ids = {row["segmentId"] for row in item.get("measurementSeries", [])}
        if (not isinstance(selected, list) or not 1 <= len(selected) <= 12
                or any(not isinstance(identity, str) for identity in selected)
                or len(selected) != len(set(selected)) or any(identity not in valid_ids for identity in selected)):
            raise ValueError("Segment IDs must belong to this session and contain 1–12 distinct windows")
        measured_ids = {row["segmentId"] for row in item["measurementSeries"]
                        if row["value"] is not None}
        if len(measured_ids) > 2 and measured_ids.issubset(selected):
            raise ValueError("Segment review must leave a measured comparison window outside the selected interval")
        if identity in {"pitch_change", "pitch_variability"}:
            first_start = min(row.startMs for row in state.request.segments if row.segmentId in selected)
            earlier = [row for row in state.request.segments
                       if row.endMs <= first_start
                       and metric(row, item["modality"], item["metric"]) is not None]
            if _independent_count(earlier) < 2:
                raise ValueError("Pitch change review needs repeated earlier comparison measurements")
        weak = _weak_measurement_context(state)
        if weak is not None:
            if (set(selected) & set(weak["reviewSegmentIds"])
                    and identity not in weak["sameIntervalAlternatives"]):
                raise ValueError("No independently valid alternative in the weak review interval")
            chosen_rows = [row for row in state.request.segments if row.segmentId in selected]
            values = [metric(row, item["modality"], item["metric"]) for row in chosen_rows]
            values = [value for value in values if value is not None]
            earlier = [metric(row, item["modality"], item["metric"])
                       for row in state.request.segments
                       if row.endMs <= min(chosen.startMs for chosen in chosen_rows)
                       and metric(row, item["modality"], item["metric"]) is not None]
            if values and len(set(values + earlier)) == 1:
                raise ValueError("Selected interval has no measured feature change")
    if action == "analyze_concept":
        eligible, reason = _concept_eligible(item)
        if not eligible:
            raise ValueError(reason)
        weak = _weak_measurement_context(state)
        if weak is not None and identity not in weak["sameIntervalAlternatives"]:
            raise ValueError("No independently repeated concept change in the weak review interval")
    if action == "compare_previous_session" and not _has_comparison(state, identity):
        raise ValueError("Previous session is not comparable")
    if action == "retrieve_papers":
        eligible, reason = _paper_eligible(state, item, rag)
        if not eligible:
            raise ValueError(reason)
        if raw.get("claimKind") not in {"interpretation", "practice"}:
            raise ValueError("Unsupported claim kind")
    return {"action": action, "candidateId": identity,
            **({"segmentIds": raw["segmentIds"]} if action == "analyze_segment" and "segmentIds" in raw else {}),
            **({"claimKind": raw["claimKind"]} if action == "retrieve_papers" else {})}


# 6. 실행 로그: 제안, 거절 이유, 실제 실행 결과를 남김.

def _observed_result(state: AgentState) -> dict | None:
    """Compact, factual tool output available when the next action is chosen."""
    if not state.actions:
        return None
    previous = state.actions[-1]
    result = previous["result"]
    return {"step": previous["step"], "tool": previous["action"],
            "candidateId": previous["candidateId"],
            **{key: result[key] for key in ("observedValue", "referenceValue",
                                            "measurementQuality", "independentObservations",
                                            "relationship", "conceptObservationCount",
                                            "support", "comparable", "difference")
               if key in result}}


def _proposal_view(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {"action": str(type(raw).__name__)}
    return {key: value for key in ("action", "candidateId", "segmentIds", "claimKind", "priorityCandidateIds")
            if (value := raw.get(key)) is not None}


def _decision_log(state: AgentState, action: dict, source: str,
                  proposals: list[dict], step: int) -> dict:
    weak = _weak_measurement_context(state)
    validation = ("accepted" if source != "fallback" else
                  "fallback_after_rejection" if any(p["serverValidation"] == "rejected" for p in proposals) else
                  "fallback_after_service_error" if any(p["serverValidation"] == "unavailable" for p in proposals) else
                  "fallback_policy")
    return {"step": step, "validCandidateIds": [item["id"] for item in state.candidates],
            "conceptEligibleCandidateIds": [item["id"] for item in state.candidates
                                            if _concept_eligible(item)[0]
                                            and ("analyze_concept", item["id"]) not in state.seen
                                            and (weak is None or item["id"] in weak["sameIntervalAlternatives"])],
            "remainingActions": MAX_ACTIONS - len(state.actions),
            "observedResult": _observed_result(state),
            "proposals": proposals, "selectedAction": action.copy(),
            "selectedCandidateId": action.get("candidateId"),
            "source": source,
            "serverValidation": validation}


# 7. Agent 반복 실행: 행동 선택 → 검증 → 도구 실행 → 상태 갱신.

def run_agent(request: ReviewRequest, summary: dict, candidates: list[dict], rag=None,
              decide: Callable | None = None, prior: dict | None = None,
              model_version: str = "unknown", decision_provider: str = "callback") -> AgentState:
    state = AgentState(request=request, summary=summary, candidates=candidates, prior=prior,
                       model_version=model_version)
    if not state.candidates:
        state.stop_reason = "no_valid_candidate"
        return state
    if summary["coverage"] < .5:
        state.stop_reason = "insufficient_coverage"
        return state
    decider_active = decide is not None
    for step in range(MAX_ACTIONS):
        action = None
        source = decision_provider
        proposals = []
        if decider_active:
            for attempt in range(MAX_DECISION_ATTEMPTS):
                proposed = None
                try:
                    proposed = decide(_decision_view(state, rag))
                    if (decision_provider == "luxia" and isinstance(proposed, dict)
                            and proposed.get("action") == "analyze_segment"
                            and "segmentIds" not in proposed):
                        raise ValueError("Luxia must select segmentIds for segment analysis")
                    action = _validate_action(proposed, state, rag)
                    proposals.append({"proposedAction": _proposal_view(proposed),
                                      "serverValidation": "accepted"})
                    state.decision_errors.clear()
                    break
                except ValueError as error:
                    proposals.append({"proposedAction": _proposal_view(proposed),
                                      "serverValidation": "rejected", "reason": str(error)[:160]})
                    state.decision_errors.append(str(error)[:160])
                    logger.warning("Agent decision rejected (%s: %s), retry %s",
                                   type(error).__name__, str(error)[:160], attempt + 1)
                except Exception as error:
                    proposals.append({"proposedAction": _proposal_view(proposed),
                                      "serverValidation": "unavailable",
                                      "reason": type(error).__name__})
                    logger.warning("Agent decision unavailable (%s); using bounded fallback", type(error).__name__)
                    decider_active = False
                    break
        if action is None:
            action = _validate_action(_safe_next_action(state, rag), state, rag)
            source = "fallback"
            proposals.append({"proposedAction": action.copy(),
                              "serverValidation": "accepted_fallback"})
        state.decisions.append(_decision_log(state, action, source, proposals, step + 1))
        if action["action"] == "finish":
            state.selected_ids = action["priorityCandidateIds"]
            inspected = [state.candidate(row["candidateId"]) for row in state.actions
                         if row["action"] == "analyze_segment"]
            missing_channel = any(not row.quality.audioValid or not row.quality.faceDetected
                                  for row in state.request.segments)
            state.stop_reason = ("decision_unavailable" if source == "fallback" else
                                 "no_valid_finding" if not state.selected_ids
                                 and ((inspected and all(item["measurementQuality"] < .8
                                                         or item["independentObservations"] < 2
                                                         or item.get("coherentShiftCount", 2) < 2
                                                         for item in inspected))
                                      or (not inspected and missing_channel))
                                 else "finished")
            break
        identity = action["candidateId"]
        item = state.candidate(identity)
        name = action["action"]
        if name == "analyze_segment":
            result = _segment_result(state, item, action.get("segmentIds"))
        elif name == "analyze_concept":
            result = _concept_result(state, item)
        elif name == "compare_previous_session":
            result = _comparison_result(state, item)
        else:
            result, hits = _paper_result(item, rag, action["claimKind"])
            state.hits[identity] = hits
        state.findings.setdefault(identity, []).append({"tool": name, "result": result})
        state.seen.add((name, identity))
        state.actions.append({"step": step + 1, **action, "result": result})
    if not state.selected_ids and state.stop_reason == "action_limit" and decider_active:
        try:
            final = _validate_action(decide(_decision_view(state, rag)), state, rag)
            if final["action"] == "finish":
                state.decisions.append(_decision_log(
                    state, final, decision_provider,
                    [{"proposedAction": final.copy(), "serverValidation": "accepted"}],
                    len(state.actions) + 1))
                state.selected_ids = final["priorityCandidateIds"]
                state.stop_reason = "finished"
        except Exception as error:
            logger.warning("Agent final selection unavailable (%s)", type(error).__name__)
    return state


# 8. 구조화 Memory: 검증된 결과와 다음 세션 목표를 저장할 형태로 정리.

def build_memory(report: dict, state: AgentState) -> dict:
    focus = next((item for item in report["priorities"] if item.get("recommendation")
                  and item.get("evidenceStatus") == "cited_excerpt"
                  and not (item["assessment"]["adviceMode"] == "review"
                           and item["id"] in {"brow_tension", "lip_tension", "gaze"})), None)
    ordered = sorted(state.candidates, key=lambda item: (item["id"] != focus["id"] if focus else True,
                                                      item["id"]))
    entries = []
    for item in ordered:
        value, count, quality = _session_measurement(state.request, item)
        entries.append({"candidateId": item["id"], "metric": item["metric"],
                        "observedValue": value, "observationCount": count,
                        "measurementQuality": quality})
    goal = ({"candidateId": focus["id"], "metric": focus["metric"],
             "action": focus["recommendation"]} if focus else None)
    return {"sessionId": report["sessionId"], "modelVersion": state.model_version,
            "metricDefinitionVersion": METRIC_DEFINITION_VERSION,
            "sceneLabel": state.request.sceneLabel, "durationMs": state.request.durationMs,
            "candidates": entries,
            "focusGoal": goal}
