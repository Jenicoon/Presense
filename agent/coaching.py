"""Server-owned coaching state, calculations and safe component contracts.

The reference renderer remains available for offline testing and compatibility.
LLM-authored coaching uses the same state transitions and component validation.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

from .coaching_methods import (
    METHODS,
    REASK_INTENTION,
    PracticeStrategy,
    ReviewOutcome,
    attach_coaching_path,
    prepare_review_request,
    profile,
)
from .practice_rubric import DeliveryReview, VERSION as RUBRIC_VERSION, checks_for, check_catalog, review_outcome, next_instruction
from .presentation_guidance import guidance, session_summary
from .report_schema import Contract, ReviewRequest
from .session_analyzer import _independent_count, intervals, metric

Action = Literal[
    "review",
    "jump_to_video",
    "explain_finding",
    "show_measurements",
    "create_practice",
    "start_recording",
    "finish_recording",
    "compare_attempts",
    "retry_practice",
    "choose_next_goal",
    "compare_previous_session",
    "finish_coaching",
    "ask",
    "confirm_intent",
    "submit_review",
    "guide_review",
    "explain_score",
    "submit_practice_review",
    "assess_delivery_achieved",
    "assess_delivery_partial",
    "assess_delivery_retry",
]
Stage = Literal[
    "session_review",
    "finding_selected",
    "practice_created",
    "recording",
    "evaluating",
    "comparison_ready",
    "next_goal",
    "completed",
]


class CoachRequest(Contract):
    sessionId: str = Field(min_length=1, max_length=100)
    action: Action = "ask"
    message: str = Field(default="", max_length=1200)
    findingId: str | None = Field(default=None, max_length=100)
    attemptSessionId: str | None = Field(default=None, max_length=100)
    language: Literal["ko", "en"] = "ko"
    revision: int | None = Field(default=None, ge=0)
    # Echoes are context only. The database state is authoritative.
    conversationState: dict = Field(default_factory=dict, max_length=10)
    previousAction: Action | None = None
    reviewOutcome: ReviewOutcome | None = None
    practiceStrategyId: PracticeStrategy | None = None
    deliveryReview: DeliveryReview | None = None


class ConversationState(Contract):
    sessionId: str
    selectedFindingId: str | None = None
    activePracticeId: str | None = None
    attemptSessionId: str | None = None
    stage: Stage = "session_review"
    nextGoalId: str | None = None
    lastAction: Action | None = None
    reviewFeedback: Literal["intentional", "needs_practice", "unsure"] | None = None
    reviewOutcome: ReviewOutcome | None = None
    practiceStrategyId: PracticeStrategy | None = None


class Choice(Contract):
    id: str
    label: str
    action: Action
    findingId: str | None = None
    reviewOutcome: ReviewOutcome | None = None
    practiceStrategyId: PracticeStrategy | None = None


class Choices(Contract):
    type: Literal["action_choices"]
    choices: list[Choice] = Field(max_length=10)


class SegmentCard(Contract):
    type: Literal["video_segment"]
    sessionId: str
    findingId: str | None = None
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)
    label: str


class FindingCard(Contract):
    type: Literal["finding"]
    findingId: str
    label: str


class PracticeCard(Contract):
    type: Literal["practice"]
    practiceId: str
    label: str
    instruction: str
    criterion: str
    durationSeconds: int
    successChecks: list[str] = Field(default_factory=list, max_length=3)


class PracticeReviewCard(Contract):
    type: Literal["practice_review"]
    practiceId: str
    attemptSessionId: str
    checks: list[dict[str, str]] = Field(min_length=2, max_length=3)


class ComparisonCard(Contract):
    type: Literal["comparison"]
    comparison: dict


class Notice(Contract):
    type: Literal["insufficient_data"]
    label: str


class ReviewGuideCard(Contract):
    type: Literal["review_guide"]
    findingId: str
    title: str = Field(min_length=1, max_length=180)
    steps: list[str] = Field(min_length=2, max_length=4)


class CoachingPathCard(Contract):
    type: Literal["coaching_path"]
    findingId: str
    title: str = Field(min_length=1, max_length=180)
    instruction: str = Field(min_length=1, max_length=900)


Component = Annotated[
    Choices
    | SegmentCard
    | FindingCard
    | PracticeCard
    | PracticeReviewCard
    | ComparisonCard
    | Notice
    | ReviewGuideCard
    | CoachingPathCard,
    Field(discriminator="type"),
]


class Generation(Contract):
    source: Literal["ai", "system"] = "system"
    provider: str | None = None
    model: str | None = None
    validated: bool = False
    dataOrigin: Literal["recorded", "synthetic", "stressid"] = "recorded"
    evidenceIds: list[str] = Field(default_factory=list, max_length=8)


class CoachResponse(Contract):
    message: str
    components: list[Component] = Field(max_length=24)
    conversationState: ConversationState
    revision: int
    generation: Generation = Field(default_factory=Generation)


def new_document(request: ReviewRequest, report: dict, version: str) -> dict:
    return {
        "snapshot": {
            "request": request.model_dump(),
            "report": report,
            "modelVersion": version,
            "conceptDefinitionVersion": request.conceptDefinitionVersion or "legacy-seven-v1",
            "metricDefinitionVersion": report.get("agentMemory", {}).get(
                "metricDefinitionVersion", request.metricDefinitionVersion
            ),
        },
        "state": ConversationState(sessionId=request.sessionId).model_dump(),
        "practices": [],
        "messages": [],
        "revision": 0,
    }


def practice_card(practice, ko):
    content = practice.get("translations", {}).get("ko" if ko else "en", practice)
    return {"type": "practice", "practiceId": practice["id"],
            **{key: content.get(key, []) if key == "successChecks" else content[key]
               for key in ("label", "instruction", "criterion", "durationSeconds", "successChecks")}}


def measurement_name(key, ko):
    from .model_contract import RAW_METRICS
    from ai.concept_registry import PROPOSED_CONCEPTS_V2
    for (_,raw_key,_,label),definition in zip(RAW_METRICS,PROPOSED_CONCEPTS_V2):
        if key==raw_key:
            return label.split(" / ")[0 if ko else 1]
        if key==definition.model_name_ko:
            return (definition.public_label_ko+" 예측값") if ko else (label.split(" / ")[1]+" prediction")
    names = {
        "f0_mean": ("평균 목소리 높이 (Hz)", "Mean voice pitch (Hz)"),
        "f0_std": ("목소리 높이 변동 (Hz)", "Voice pitch variation (Hz)"),
        "voiced_ratio": ("유성음 비율", "Voiced audio ratio"),
        "energy_variability": ("음성 에너지 변화", "Voice energy variation"),
        "lip_tension": ("입 벌림 비율", "Mouth aperture ratio"),
        "brow_tension": ("눈썹 움직임 추정치", "Brow movement estimate"),
        "eye_contact_score": ("시선 안정도 추정치", "Gaze stability estimate"),
        "gaze_stability": ("시선 안정도 추정치", "Gaze stability estimate"),
        "head_movement": ("머리 움직임 추정치", "Head movement estimate"),
        "mean_ear": ("눈 열림 추정치", "Eye opening estimate"),
        "blink_count": ("눈 감김 프레임 추정치", "Closed-eye frame estimate"),
    }
    names.update(
        {
            "voice": ("목소리 패턴", "Voice pattern"),
            "목소리 거칠기": ("목소리 거칠기 패턴", "Voice roughness pattern"),
            "음색 불안정성": ("음색 변화 패턴", "Voice timbre variation pattern"),
            "음성 두께": ("음성 두께 패턴", "Voice depth pattern"),
            "음성 피치": ("목소리 높이 패턴", "Voice pitch pattern"),
            "표정 변화량": ("표정 변화 패턴", "Facial movement pattern"),
            "입술 긴장도": ("입술 모양 패턴", "Lip shape pattern"),
            "눈썹 찡그림": ("눈썹 움직임 패턴", "Brow movement pattern"),
        }
    )
    return names.get(
        key,
        (
            "추가 관측값",
            key.replace("_", " ") if key.isascii() else "Additional measurement",
        ),
    )[0 if ko else 1]


def label(finding, ko):
    parts = finding["label"].split(" / ")
    return parts[0] if ko else parts[-1]


def _stats(snapshot, modality=None, key=None, ranges=None):
    request = ReviewRequest.model_validate(snapshot["request"])
    rows = request.segments
    if ranges:
        rows = [
            s
            for s in rows
            if any(s.startMs >= r["startMs"] and s.endMs <= r["endMs"] for r in ranges)
        ]
    valid = [
        s
        for s in rows
        if (
            metric(s, modality, key) is not None
            if modality
            else s.quality.audioValid or s.quality.faceDetected
        )
    ]
    total = weighted = 0
    for start, end, active in intervals(valid):
        total += end - start
        weighted += (
            (end - start)
            * sum(
                metric(valid[i], modality, key) if modality else valid[i].stressScore
                for i in active
            )
            / len(active)
        )
    duration = (
        sum(r["endMs"] - r["startMs"] for r in ranges) if ranges else request.durationMs
    )
    return {
        "value": round(weighted / total, 6) if total else None,
        "observedMs": total,
        "coverage": total / max(duration, 1),
        "independentObservations": _independent_count(valid),
        "windowCount": len(valid),
        "quality": (
            len(valid)
            if modality
            else sum(s.quality.audioValid and s.quality.faceDetected for s in rows)
        )
        / max(len(rows), 1),
    }


def compare_snapshots(before, after, practice=None):
    """Identical time-weighted statistics and quality rules for every comparison."""
    compatible = (
        before["modelVersion"] != "unknown"
        and before["modelVersion"] == after["modelVersion"]
        and before["metricDefinitionVersion"] == after["metricDefinitionVersion"]
        and before.get("conceptDefinitionVersion", "legacy-seven-v1") == after.get("conceptDefinitionVersion", "legacy-seven-v1")
        and bool(before["request"].get("sceneLabel"))
        and before["request"].get("sceneLabel") == after["request"].get("sceneLabel")
    )
    ranges = practice.get("ranges") if practice else None
    a, b = _stats(before, ranges=ranges), _stats(after)
    if not practice:
        compatible = (
            compatible
            and 0.5
            <= after["request"]["durationMs"] / before["request"]["durationMs"]
            <= 2
        )
    sufficient = compatible and all(
        s["coverage"] >= 0.5
        and s["independentObservations"] >= 2
        and s["quality"] >= 0.8
        for s in (a, b)
    )
    changes = []
    for modality, field in (
        ("audio", "audioFeatures"),
        ("video", "videoFeatures"),
        ("concept", "concepts"),
    ):
        common = set.intersection(
            *[
                {k for s in snap["request"]["segments"] for k in s[field]}
                for snap in (before, after)
            ]
        )
        for key in sorted(common):
            first, second = (
                _stats(before, modality, key, ranges),
                _stats(after, modality, key),
            )
            if first["value"] is not None and second["value"] is not None:
                changes.append(
                    {
                        "modality": modality,
                        "metric": key,
                        "before": first["value"],
                        "after": second["value"],
                        "difference": round(second["value"] - first["value"], 6),
                        "beforeCount": first["independentObservations"],
                        "afterCount": second["independentObservations"],
                        "beforeQuality": first["quality"],
                        "afterQuality": second["quality"],
                        "beforeCoverage": first["coverage"],
                        "afterCoverage": second["coverage"],
                    }
                )
    outcome, improvement = "insufficient_data", None
    reference = practice.get("referenceValue") if practice else None
    focus = next(
        (
            x
            for x in changes
            if practice
            and x["metric"] == practice["metric"]
            and x["modality"] == practice["modality"]
        ),
        None,
    )
    delivery_review = bool(
        practice and practice.get("evaluationMode") == "delivery_review"
    )
    if delivery_review:
        eligible = (
            sufficient
            and focus
            and min(focus["beforeCount"], focus["afterCount"]) >= 2
            and min(focus["beforeQuality"], focus["afterQuality"]) >= 0.8
            and min(focus["beforeCoverage"], focus["afterCoverage"]) >= 0.5
        )
        if eligible:
            outcome = (review_outcome(practice["deliveryReview"]) if practice.get("deliveryReview")
                       else practice.get("deliveryAssessment") or "review_required")
    elif (
        sufficient
        and focus
        and reference is not None
        and abs(focus["before"] - reference) > 1e-6
        and min(focus["beforeCount"], focus["afterCount"]) >= 2
        and min(focus["beforeQuality"], focus["afterQuality"]) >= 0.8
    ):
        improvement = 1 - abs(focus["after"] - reference) / abs(
            focus["before"] - reference
        )
        outcome = (
            "achieved"
            if improvement >= 0.2
            else "partial"
            if improvement > 0
            else "retry_recommended"
        )
    elif sufficient and not practice:
        outcome = "comparable"
    review = practice.get("deliveryReview") if practice else None
    conditions_match = not review or (review["sameContent"] == "same" and review["sameEnvironment"] == "same")
    return {
        "deliveryReview": review,
        "reviewChecks": check_catalog(practice) if practice and practice.get("rubricVersion") else [],
        "conditionsConfirmed": bool(review and conditions_match),
        "previousSessionId": before["request"]["sessionId"],
        "currentSessionId": after["request"]["sessionId"],
        "outcome": outcome,
        "compatible": compatible,
        "scope": "practice" if practice else "previous_session",
        "before": a,
        "after": b,
        "modelScoreChange": round(b["value"] - a["value"], 6) if sufficient and conditions_match else None,
        "measurements": changes if compatible and conditions_match else [],
        "referenceValue": reference,
        "evaluationMode": "delivery_review"
        if delivery_review
        else "measurement_comparison",
        "assessmentSource": "presenter"
        if delivery_review
        and (practice.get("deliveryAssessment") or review)
        else "none",
        "criterion": "presenter_delivery_review"
        if delivery_review
        else "relative_deviation_reduction_20pct"
        if practice
        else "same_metric_descriptive_comparison",
        "formula": ""
        if delivery_review
        else "1 - |current - reference| / |previous - reference|; ≥ 0.20 achieved, > 0 partial, otherwise retry",
        "note": "Selected measurement goal only; a lower model score or pitch does not prove better delivery.",
    }


def validate_response(raw, doc, attempt=None, previous=None):
    response = CoachResponse.model_validate(raw)
    state = response.conversationState
    if state.sessionId != doc["state"]["sessionId"]:
        raise ValueError("Cross-session state")
    finding_map = {f["id"]: f for f in doc["snapshot"]["report"]["priorities"]}
    findings = set(finding_map)
    if state.nextGoalId and state.nextGoalId not in findings:
        raise ValueError("Unknown next goal")
    if state.selectedFindingId and state.selectedFindingId not in findings:
        raise ValueError("Unknown selected finding")
    practices = {p["id"]: p for p in doc["practices"]}
    if state.activePracticeId and state.activePracticeId not in practices:
        raise ValueError("Unknown practice")
    for component in response.components:
        if isinstance(component, SegmentCard):
            snapshots = (
                [doc["snapshot"]]
                + ([attempt["snapshot"]] if attempt else [])
                + ([previous["snapshot"]] if previous else [])
            )
            snap = next(
                (
                    s
                    for s in snapshots
                    if s["request"]["sessionId"] == component.sessionId
                ),
                None,
            )
            if not snap or not any(
                s["startMs"] == component.startMs and s["endMs"] == component.endMs
                for s in snap["request"]["segments"]
            ):
                raise ValueError("Video interval was not observed")
            if component.findingId:
                finding = finding_map.get(component.findingId)
                if (
                    not finding
                    or component.sessionId != state.sessionId
                    or not any(
                        o["startMs"] == component.startMs
                        and o["endMs"] == component.endMs
                        for o in finding["observations"]
                    )
                ):
                    raise ValueError(
                        "Video is not supporting evidence for this finding"
                    )
        elif isinstance(component, FindingCard) and component.findingId not in findings:
            raise ValueError("Unknown finding")
        elif isinstance(component, (ReviewGuideCard, CoachingPathCard)):
            if component.findingId not in findings:
                raise ValueError("Unknown review guide finding")
        elif isinstance(component, PracticeCard):
            p = practices.get(component.practiceId)
            content = {
                k: getattr(component, k)
                for k in ("label", "instruction", "criterion", "durationSeconds", "successChecks")
            }
            allowed = (
                (
                    [{k: p.get(k, []) if k == "successChecks" else p[k] for k in content}]
                    + [{**value, "successChecks": value.get("successChecks", [])} for value in p.get("translations", {}).values()]
                )
                if p
                else []
            )
            if content not in allowed:
                raise ValueError("Unknown or altered exercise")
        elif isinstance(component, PracticeReviewCard):
            p = practices.get(component.practiceId)
            if (not p or component.practiceId != state.activePracticeId or state.stage != "comparison_ready"
                    or component.attemptSessionId != state.attemptSessionId
                    or component.attemptSessionId != p.get("attemptSessionId")
                    or component.checks not in [checks_for(p, True), checks_for(p, False)]):
                raise ValueError("Unsupported practice review")
        elif isinstance(component, ComparisonCard):
            is_attempt = (
                component.comparison.get("previousSessionId") == state.sessionId
            )
            p = practices.get(state.activePracticeId) if is_attempt else None
            target = attempt if is_attempt else previous
            if not target or component.comparison != (
                compare_snapshots(doc["snapshot"], target["snapshot"], p)
                if p
                else compare_snapshots(target["snapshot"], doc["snapshot"])
            ):
                raise ValueError("Comparison contains unsupported measurements")
        elif isinstance(component, Choices):
            if any(
                c.findingId and c.findingId not in findings for c in component.choices
            ):
                raise ValueError("Unknown choice finding")
            for choice in component.choices:
                finding = finding_map.get(choice.findingId or state.selectedFindingId)
                if choice.action == "submit_review" and (
                    not finding
                    or choice.reviewOutcome
                    not in {row[0] for row in profile(finding)["outcomes"]}
                ):
                    raise ValueError("Unsupported review outcome choice")
                if choice.practiceStrategyId and (
                    choice.action != "create_practice"
                    or not finding
                    or choice.practiceStrategyId not in profile(finding)["strategies"]
                ):
                    raise ValueError("Unsupported practice method choice")
    for finding_id in {
        c.findingId
        for c in response.components
        if isinstance(c, SegmentCard) and c.findingId
    }:
        shown = [
            (c.startMs, c.endMs)
            for c in response.components
            if isinstance(c, SegmentCard) and c.findingId == finding_id
        ]
        expected = [
            (o["startMs"], o["endMs"]) for o in finding_map[finding_id]["observations"]
        ]
        if sorted(shown) != sorted(expected):
            raise ValueError(
                "Supporting observation videos must not be omitted or duplicated"
            )
    return response.model_dump()


def route_question(message, route=None, context=None):
    # Optional LLM selects only an intent, never user-visible factual prose.
    allowed = {
        "explain_finding",
        "show_measurements",
        "jump_to_video",
        "create_practice",
        "compare_previous_session",
        "compare_attempts",
        "review",
        "confirm_intent",
        "guide_review",
        "explain_score",
    }
    # Explicit answers from the presenter can be understood without fabricating facts.
    text = message.lower().strip()
    if any(
        word in text
        for word in ("모르겠", "어떻게 봐", "how to review", "help me review")
    ):
        return "guide_review"
    if any(
        word in text
        for word in (
            "의도한 표현이었",
            "일부러 강조",
            "that was intentional",
            "on purpose",
        )
    ):
        return "confirm_intent"
    if any(word in text for word in ("점수", "score")) and not any(
        word in text
        for word in ("어디", "구간", "where", "interval", "이전", "previous")
    ):
        return "explain_score"
    if route:
        try:
            result = route(
                {
                    "question": message,
                    "allowedActions": sorted(allowed),
                    "conversationState": context or {},
                }
            )
            if result.get("action") in allowed or result.get("action") == "unknown":
                return result["action"]
        except Exception as error:  # noqa: BLE001 - optional provider; deterministic routing remains available
            import logging

            logging.getLogger(__name__).info(
                "Coach intent routing unavailable (%s)", type(error).__name__
            )
    text = message.lower()
    for words, action in [
        (("이전", "나아", "previous"), "compare_previous_session"),
        (("다시 촬영", "평가", "compare", "evaluate"), "compare_attempts"),
        (("왜", "이유", "why"), "explain_finding"),
        (("음성", "표정", "측정", "measure", "voice"), "show_measurements"),
        (("영상", "보여", "video"), "jump_to_video"),
        (("연습", "문제", "practice"), "create_practice"),
        (("불안정", "어디", "where", "unstable"), "review"),
    ]:
        if any(w in text for w in words):
            return action
    return "unknown"


def _respond(doc, request: CoachRequest, *, attempt=None, previous=None, route=None):
    doc = deepcopy(doc)
    if request.sessionId != doc["state"]["sessionId"]:
        raise ValueError("Session identity mismatch")
    ko = request.language == "ko"
    state = ConversationState.model_validate(doc["state"])
    findings = doc["snapshot"]["report"]["priorities"][:3]
    if request.findingId:
        if (
            state.stage in {"recording", "evaluating"}
            and request.findingId != state.selectedFindingId
        ):
            raise ValueError("Finish the active practice before switching goals")
        if request.findingId not in {f["id"] for f in findings}:
            raise ValueError("Unknown finding")
        if state.selectedFindingId != request.findingId:
            state.reviewFeedback = None
            state.reviewOutcome = None
            state.practiceStrategyId = None
        state.selectedFindingId = request.findingId
        if state.stage in {
            "session_review",
            "finding_selected",
            "next_goal",
            "completed",
        }:
            state.stage = "finding_selected"
    finding = next((f for f in findings if f["id"] == state.selectedFindingId), None)
    action = (
        route_question(request.message, route, state.model_dump())
        if request.action == "ask"
        else request.action
    )
    components = []

    def choice(action, korean, english, finding_id=None):
        return {
            "id": action + (finding_id or ""),
            "label": korean if ko else english,
            "action": action,
            "findingId": finding_id,
        }

    def choices(*items):
        components.append({"type": "action_choices", "choices": list(items)})

    def segment(snap, row, card_label=None):
        components.append(
            {
                "type": "video_segment",
                "sessionId": snap["request"]["sessionId"],
                "startMs": row["startMs"],
                "endMs": row["endMs"],
                "label": card_label
                or ("이 구간 확인하기" if ko else "Review this interval"),
            }
        )

    practice = next(
        (p for p in doc["practices"] if p["id"] == state.activePracticeId), None
    )
    message = ""
    if action == "review":
        report = doc["snapshot"]["report"]
        message = session_summary(report, ko)
        if findings:
            message += (
                " 먼저 이 관찰을 확인해 보세요."
                if ko
                else " Start with this observation."
            )
            first = next(
                (
                    s
                    for s in doc["snapshot"]["request"]["segments"]
                    if s["segmentId"] == findings[0]["observations"][0]["segmentId"]
                ),
                None,
            )
            if first:
                segment(doc["snapshot"], first)
            for f in findings:
                components.append(
                    {
                        "type": "finding",
                        "findingId": f["id"],
                        "label": guidance(f, ko)["title"],
                    }
                )
            choices(
                choice(
                    "explain_finding",
                    "이 구간 함께 확인하기",
                    "Review this interval together",
                    findings[0]["id"],
                ),
                choice(
                    "compare_previous_session",
                    "이전 세션과 비교",
                    "Compare previous session",
                ),
            )
        else:
            message = (
                "이번 세션에서는 반복적으로 확인된 주요 문제를 찾지 못했습니다."
                if ko
                else "No repeatedly observed major issue was found in this session."
            )
            if doc["snapshot"]["report"]["analysis"]["coverage"] < 0.5:
                components.append(
                    {
                        "type": "insufficient_data",
                        "label": "분석 자료가 부족합니다."
                        if ko
                        else "Insufficient analysis coverage.",
                    }
                )
            else:
                message += (
                    " 낮거나 안정적인 구간도 타임라인에서 확인할 수 있습니다."
                    if ko
                    else " Low or stable intervals remain on the timeline."
                )
            choices(
                choice(
                    "compare_previous_session",
                    "이전 세션과 비교",
                    "Compare previous session",
                ),
                choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"),
            )
    elif action in {"explain_finding", "show_measurements", "jump_to_video"}:
        finding = finding or next(iter(findings), None)
        if finding:
            state.selectedFindingId = finding["id"]
            if state.stage == "session_review":
                state.stage = "finding_selected"
            view = guidance(finding, ko)
            message = view["observation"] + " " + view["question"]
            rows = [
                s
                for s in doc["snapshot"]["request"]["segments"]
                if s["segmentId"] in {o["segmentId"] for o in finding["observations"]}
            ]
            if rows:
                segment(
                    doc["snapshot"],
                    rows[0],
                    "변화가 나타난 구간 듣기"
                    if ko
                    else "Listen to the changed interval",
                )
                earlier = next(
                    (
                        row
                        for row in doc["snapshot"]["request"]["segments"]
                        if row["endMs"] <= rows[0]["startMs"]
                        and metric(
                            ReviewRequest.model_validate(
                                doc["snapshot"]["request"]
                            ).segments[
                                doc["snapshot"]["request"]["segments"].index(row)
                            ],
                            finding["modality"],
                            finding["metric"],
                        )
                        is not None
                    ),
                    None,
                )
                if earlier:
                    segment(
                        doc["snapshot"],
                        earlier,
                        "앞부분과 비교해 듣기"
                        if ko
                        else "Compare with an earlier interval",
                    )
            if action == "show_measurements":
                for row in rows[:3]:
                    values = []
                    for modality, field in (
                        ("audio", "audioFeatures"),
                        ("video", "videoFeatures"),
                        ("concept", "concepts"),
                    ):
                        parsed = ReviewRequest.model_validate(
                            doc["snapshot"]["request"]
                        )
                        obs = next(
                            s
                            for s in parsed.segments
                            if s.segmentId == row["segmentId"]
                        )
                        values += [
                            f"{measurement_name(k, ko)}: {v:.3f}"
                            for k in row[field]
                            if (v := metric(obs, modality, k)) is not None
                        ]
                    message += (
                        "\n"
                        + f"{row['startMs'] / 1000:g}–{row['endMs'] / 1000:g}s"
                        + " · "
                        + "; ".join(values)
                    )
            choices(
                choice("confirm_intent", "의도한 표현이었어요", "That was intentional"),
                choice(
                    "create_practice",
                    "이 부분을 연습하고 싶어요",
                    "I'd like to practice this",
                ),
                choice(
                    "guide_review", "무엇을 들어야 할지 모르겠어요", "Help me review it"
                ),
                choice(
                    "show_measurements",
                    "분석 근거 자세히 보기",
                    "Show analysis evidence",
                ),
            )
        else:
            message = (
                "선택할 주요 발견이 없습니다."
                if ko
                else "No finding is available to select."
            )
        if not finding:
            peak = (
                doc["snapshot"]["report"]
                .get("observationReport", {})
                .get("peakSegment")
            )
            if peak:
                row = next(
                    s
                    for s in doc["snapshot"]["request"]["segments"]
                    if s["segmentId"] == peak["segmentId"]
                )
                segment(doc["snapshot"], row)
                message = (
                    f"이 구간의 모델 점수는 {row['stressScore']:.3f}입니다. 개선 문제나 원인을 확정한 것은 아닙니다."
                    if ko
                    else f"The model score in this interval is {row['stressScore']:.3f}. This does not establish a problem or cause."
                )
                if action == "show_measurements":
                    parsed = ReviewRequest.model_validate(doc["snapshot"]["request"])
                    obs = next(
                        s for s in parsed.segments if s.segmentId == row["segmentId"]
                    )
                    friendly = {
                        "f0_mean": ("평균 목소리 높이 (Hz)", "Mean voice pitch (Hz)"),
                        "f0_std": (
                            "목소리 높이 변동 (Hz)",
                            "Voice pitch variation (Hz)",
                        ),
                        "lip_tension": ("입 벌림 비율", "Mouth aperture ratio"),
                        "brow_tension": (
                            "눈썹 움직임 추정치",
                            "Brow movement estimate",
                        ),
                        "eye_contact_score": (
                            "시선 안정도 추정치",
                            "Gaze stability estimate",
                        ),
                    }
                    for modality, field in (
                        ("audio", "audioFeatures"),
                        ("video", "videoFeatures"),
                        ("concept", "concepts"),
                    ):
                        message += "\n" + " · ".join(
                            f"{friendly.get(k, (k, k))[0 if ko else 1]}: {v:g}"
                            for k in row[field]
                            if (v := metric(obs, modality, k)) is not None
                        )
    elif action == "explain_score":
        mean = doc["snapshot"]["report"]["analysis"].get("averageStress")
        prefix = (
            (
                f"이번 발표의 평균 스트레스 신호는 {round(mean * 100)} / 100입니다. "
                if ko
                else f"This presentation's mean stress signal is {round(mean * 100)} / 100. "
            )
            if mean is not None
            else (
                "현재 평균을 계산할 분석 자료가 없습니다. "
                if ko
                else "There is no analyzed data for a mean score. "
            )
        )
        message = prefix + (
            "AI가 음성·영상에서 학습한 스트레스 관련 패턴을 감지한 참고값입니다. 같은 발표에서 다시 볼 구간을 찾고 같은 조건의 재촬영과 비교하는 데 사용합니다. 70점이 실제 스트레스 70%를 뜻하지 않으며, 발표 실력의 성적도 아닙니다. 평균에는 실제 분석된 시간만 반영합니다."
            if ko
            else "It is a reference measure of stress-related patterns learned by the AI from audio and video. Use it to find moments to review and compare takes under the same conditions. A score of 70 does not mean 70% actual stress or grade your presentation. The mean includes analyzed time only."
        )
    elif action in {"confirm_intent", "guide_review"}:
        finding = finding or next(iter(findings), None)
        if not finding or state.stage in {"recording", "evaluating"}:
            raise ValueError("Select a finding before reviewing delivery")
        state.selectedFindingId = finding["id"]
        state.stage = "finding_selected"
        if action == "confirm_intent":
            state.reviewFeedback = "intentional"
            state.reviewOutcome = state.reviewOutcome or "intentional"
        elif state.reviewOutcome not in {"effective", "intentional"}:
            state.reviewFeedback = "unsure"
        if action == "confirm_intent":
            message = (
                "의도한 표현으로 기록했어요. 이 변화만으로 목소리나 표정을 고칠 필요는 없습니다. 다른 확인할 부분이 없다면 이번 코칭을 마쳐도 좋습니다."
                if ko
                else "Recorded this as intentional expression. This change alone needs no correction. You can finish coaching if there is nothing else to review."
            )
            choices(
                choice(
                    "choose_next_goal", "다른 확인할 부분 보기", "Review another focus"
                ),
                choice("finish_coaching", "이번 코칭 마치기", "Finish coaching"),
            )
        else:
            view = guidance(finding, ko)
            message = (
                "먼저 앞부분과 선택 구간을 번갈아 들어보세요. 핵심 문장 한 곳만 힘주어 말했는지, 여러 문장이 계속 강하게 들리는지 확인해 보세요. 어떤 표현이 더 좋은지는 전달하려던 의도와 함께 판단하세요."
                if finding["id"].startswith("pitch") and ko
                else "Alternate between the earlier and selected intervals. Listen for one emphasized key sentence versus sustained emphasis across several sentences. Judge it against your intention."
                if finding["id"].startswith("pitch")
                else "선택 구간을 소리와 함께 보고 표정·시선이 말의 의도와 맞는지 확인해 보세요. 수치만으로 고쳐야 할 표현이라고 정하지 않습니다."
                if ko
                else "Watch with sound and check expression or gaze against what you intended to convey. A measurement alone does not establish a delivery problem."
            )
            row = next(
                (
                    r
                    for r in doc["snapshot"]["request"]["segments"]
                    if r["segmentId"] == finding["observations"][0]["segmentId"]
                ),
                None,
            )
            if row:
                segment(doc["snapshot"], row)
            choices(
                choice("confirm_intent", "의도한 표현이었어요", "That was intentional"),
                choice(
                    "create_practice", "한 번 연습해 볼게요", "Try one practice take"
                ),
            )
    elif action == "create_practice":
        finding = finding or next(iter(findings), None)
        if not finding:
            message = (
                "근거 있는 연습 목표가 없습니다. 먼저 분석 자료를 더 모아 주세요."
                if ko
                else "No supported practice goal is available. Collect more observations first."
            )
        elif state.stage in {"recording", "evaluating"}:
            raise ValueError("Finish the active recording first")
        else:
            state.selectedFindingId = finding["id"]
            practice = {
                "id": str(uuid4()),
                "findingId": finding["id"],
                "metric": finding["metric"],
                "modality": finding["modality"],
                "ranges": finding["ranges"],
                "referenceValue": finding.get("referenceValue"),
                "label": label(finding, ko),
                "instruction": (
                    "선택 구간을 보고 전달이 흐려졌는지 직접 확인하세요. 같은 내용을 같은 환경에서 30초 다시 발표하며 문장 사이에 한 번 멈춰 보세요. 높거나 낮은 음성 자체를 고칠 필요는 없습니다."
                    if ko
                    else "Review the selected interval and check delivery yourself. Repeat the same content for 30 seconds in the same scene, pausing once between sentences. Pitch height itself needs no correction."
                ),
                "criterion": (
                    "같은 측정값의 기준 대비 편차를 비교합니다. 편차가 20% 이상 줄면 달성, 조금 줄면 부분 달성입니다. 각 시도에 독립 관측 2개, 커버리지 50%, 해당 측정 품질 80%가 필요합니다. 전달력의 성적은 아닙니다."
                    if ko
                    else "Compare the same measurement's distance from the reference: ≥20% reduction achieved, >0 partial. Each take needs 2 independent windows, 50% coverage and 80% measurement quality. This does not grade delivery."
                ),
                "durationSeconds": 30,
            }
            view = guidance(finding, ko)
            if state.reviewOutcome not in {"effective", "intentional"}:
                state.reviewFeedback = "needs_practice"
            practice["strategyId"] = state.practiceStrategyId or profile(finding)["strategies"][0]
            state.practiceStrategyId = practice["strategyId"]
            practice["rubricVersion"] = RUBRIC_VERSION
            practice["reviewChecks"] = check_catalog(practice)
            practice["successChecks"] = [check["label"] for check in checks_for(practice, ko)]
            practice["reviewOutcome"] = state.reviewOutcome
            practice["evaluationMode"] = "delivery_review"
            practice["label"] = view["goal"]
            practice["instruction"] = view["instruction"]
            if state.practiceStrategyId:
                method = METHODS[state.practiceStrategyId]
                practice["label"] = method["label"][0 if ko else 1]
                practice["instruction"] = (
                    (
                        "1. 선택 구간에서 다시 말할 문장을 직접 고르세요.\n2. "
                        + method["goal"][0]
                        + ".\n3. "
                        + method["check"][0]
                        + "."
                    )
                    if ko
                    else (
                        "1. Choose a sentence from the selected interval.\n2. "
                        + method["goal"][1]
                        + ".\n3. "
                        + method["check"][1]
                        + "."
                    )
                )
            practice["criterion"] = (
                "녹화 후 두 영상을 비교해 선택한 전달 행동을 실행했는지 확인합니다. 스트레스 신호와 음성·영상 수치는 변화의 참고 자료이며, 숫자가 낮아졌다는 이유로 성공을 판정하지 않습니다."
                if ko
                else "Compare both recordings to check whether you carried out the chosen delivery action. Stress signals and measurements describe changes; lower numbers alone do not establish success."
            )
            scene = str(doc["snapshot"]["request"].get("sceneLabel") or "—")
            scene_names = {
                "Camera": ("카메라", "Camera"),
                "카메라": ("카메라", "Camera"),
                "Classroom": ("강의실", "Classroom"),
                "강의실": ("강의실", "Classroom"),
                "Interview": ("면접", "Interview"),
                "면접": ("면접", "Interview"),
                "Live Camera": ("실시간 카메라", "Live Camera"),
                "실시간 카메라": ("실시간 카메라", "Live Camera"),
                "Classroom Audience": ("강의실 청중", "Classroom Audience"),
                "강의실 청중": ("강의실 청중", "Classroom Audience"),
                "Interview Panel": ("면접 패널", "Interview Panel"),
                "면접 패널": ("면접 패널", "Interview Panel"),
                "Presentation Slides": ("발표 슬라이드", "Presentation Slides"),
                "발표 슬라이드": ("발표 슬라이드", "Presentation Slides"),
                "Slides in Classroom": ("강의실 속 슬라이드", "Slides in Classroom"),
                "강의실 속 슬라이드": ("강의실 속 슬라이드", "Slides in Classroom"),
            }
            practice["instruction"] += (
                " 같은 환경: " if ko else " Same scene: "
            ) + scene_names.get(scene, (scene, scene))[0 if ko else 1]
            doc["practices"].append(practice)
            state.activePracticeId = practice["id"]
            state.attemptSessionId = None
            state.stage = "practice_created"
            components.append(
                {
                    "type": "practice",
                    "practiceId": practice["id"],
                    **{
                        k: practice[k]
                        for k in (
                            "label",
                            "instruction",
                            "criterion",
                            "durationSeconds",
                            "successChecks",
                        )
                    },
                }
            )
            message = (
                "한 가지 목표로 짧게 다시 연습해 보세요."
                if ko
                else "Try one short exercise with one goal."
            )
            choices(
                choice(
                    "start_recording", "재연습 녹화 시작", "Start practice recording"
                )
            )
    elif action in {"start_recording", "retry_practice"}:
        allowed = (
            {"comparison_ready"}
            if action == "retry_practice"
            else {"practice_created", "recording"}
        )
        if not practice or state.stage not in allowed:
            raise ValueError(
                "Create a practice or finish the active attempt before recording"
            )
        if action == "retry_practice":
            retry_instruction = {"ko": next_instruction(practice, True), "en": next_instruction(practice, False)} if practice.get("rubricVersion") else None
            practice = deepcopy(practice)
            if retry_instruction:
                practice["retryInstruction"] = retry_instruction
            practice["id"] = str(uuid4())
            practice.pop("comparison", None)
            practice.pop("attemptSessionId", None)
            practice.pop("deliveryAssessment", None)
            practice.pop("deliveryReview", None)
            doc["practices"].append(practice)
            state.activePracticeId = practice["id"]
        state.stage = "recording"
        state.attemptSessionId = None
        message = (
            "카메라와 마이크를 확인한 후 준비 화면에서 시작하세요. 같은 환경과 내용으로 30초 이상 발표하고 종료해 주세요."
            if ko
            else "Check the camera and microphone, then start on the preparation screen. Use the same scene and content for at least 30 seconds, then finish."
        )
        if practice.get("retryInstruction"):
            message = practice["retryInstruction"]["ko" if ko else "en"] + " " + message
        components.append(practice_card(practice, ko))
        choices(choice("finish_recording", "녹화 종료 및 분석", "Finish and analyze"))
    elif action in {"finish_recording", "compare_attempts"}:
        if not practice:
            message = (
                "진행 중인 연습이 없습니다." if ko else "There is no active practice."
            )
        elif not attempt:
            if action == "finish_recording" and state.stage == "recording":
                state.stage = "evaluating"
            message = (
                "재촬영의 분석 결과가 아직 없습니다. 녹화 화면에서 종료 후 분석 완료를 기다려 주세요."
                if ko
                else "No analyzed retry is available yet. Finish recording and wait for analysis."
            )
            components.append({"type": "insufficient_data", "label": message})
        else:
            if state.stage not in {"recording", "evaluating", "comparison_ready"}:
                raise ValueError("No recording awaits evaluation")
            if attempt["snapshot"]["request"]["sessionId"] == state.sessionId:
                raise ValueError("Cannot compare a session to itself")
            if (
                practice.get("attemptSessionId")
                and practice["attemptSessionId"]
                != attempt["snapshot"]["request"]["sessionId"]
            ):
                raise ValueError("Exercise already evaluated; use retry")
            ctx = attempt["snapshot"]["request"].get("practiceContext")
            if not ctx or ctx != {
                "sessionId": state.sessionId,
                "practiceId": practice["id"],
            }:
                raise ValueError("Attempt does not belong to this exercise")
            result = compare_snapshots(doc["snapshot"], attempt["snapshot"], practice)
            practice["comparison"] = result
            practice["attemptSessionId"] = attempt["snapshot"]["request"]["sessionId"]
            state.attemptSessionId = practice["attemptSessionId"]
            state.stage = "comparison_ready"
            practice_label = practice.get("translations", {}).get("ko" if ko else "en", {}).get("label", practice["label"])
            message = (
                f"‘{practice_label}’ 재촬영 분석이 끝났어요. 원본과 이번 영상을 보고 연습 전에 정한 행동을 아래에서 하나씩 확인해 주세요."
                if ko
                else f"Your retry for '{practice_label}' is ready. Watch the original and retry, then check each action you chose before recording."
            )
            focus_change = next(
                (
                    m
                    for m in result["measurements"]
                    if m["metric"] == practice["metric"]
                    and m["modality"] == practice["modality"]
                ),
                None,
            )
            if focus_change:
                direction = focus_change["difference"]
                item = measurement_name(practice["metric"], ko)
                message += (
                    f" 관련 측정값({item})은 원본보다 {'높게' if direction > 0 else '낮게' if direction < 0 else '비슷하게'} 관측됐습니다. 자세한 수치는 아래에서 확인할 수 있어요."
                    if ko
                    else f" {item} was {'higher' if direction > 0 else 'lower' if direction < 0 else 'similar'} in the retry. Exact measurements are available below."
                )
            if result["outcome"] == "insufficient_data" and practice.get("deliveryReview"):
                message = next_instruction(practice, ko)
            elif result["outcome"] == "insufficient_data":
                message = (
                    "촬영은 끝났지만 두 시도의 분석 조건이나 자료가 충분히 맞지 않아 수치 비교를 보류했어요. 카메라·마이크와 같은 촬영 환경을 확인하고, 같은 내용을 30초 이상 다시 발표해 주세요."
                    if ko
                    else "Recording is complete, but the analysis conditions or observations do not sufficiently match for comparison. Check the camera and microphone, use the same scene and content, and present for at least 30 seconds."
                )
            components.append({"type": "comparison", "comparison": result})
            for snap, card_label, selected in (
                (
                    doc["snapshot"],
                    "원본 발표 보기" if ko else "Watch the original",
                    practice["ranges"],
                ),
                (
                    attempt["snapshot"],
                    "이번 재촬영 보기" if ko else "Watch the retry",
                    None,
                ),
            ):
                row = next(
                    (
                        r
                        for r in snap["request"]["segments"]
                        if not selected
                        or any(
                            r["startMs"] >= x["startMs"] and r["endMs"] <= x["endMs"]
                            for x in selected
                        )
                    ),
                    None,
                )
                if row:
                    segment(snap, row, card_label)
            if result["outcome"] == "review_required" and practice.get("rubricVersion"):
                components.append({"type": "practice_review", "practiceId": practice["id"],
                                   "attemptSessionId": state.attemptSessionId, "checks": checks_for(practice, ko)})
            elif result["outcome"] == "review_required":
                choices(
                    choice(
                        "assess_delivery_achieved",
                        "의도한 전달이 됐어요",
                        "I delivered it as intended",
                    ),
                    choice(
                        "assess_delivery_partial", "일부만 됐어요", "Partly as intended"
                    ),
                    choice(
                        "assess_delivery_retry", "다시 해볼게요", "I'd like to retry"
                    ),
                )
            else:
                choices(
                    choice("retry_practice", "같은 연습 다시 하기", "Retry practice"),
                    choice("choose_next_goal", "다음 목표 선택", "Choose next goal"),
                    choice(
                        "finish_coaching", "목표 저장하고 마치기", "Save and finish"
                    ),
                )
    elif action == "submit_practice_review":
        review = request.deliveryReview
        if (not practice or not attempt or not review or not practice.get("rubricVersion")
                or state.stage != "comparison_ready" or review.practiceId != state.activePracticeId
                or review.attemptSessionId != state.attemptSessionId
                or review.attemptSessionId != practice.get("attemptSessionId")
                or attempt["snapshot"]["request"]["sessionId"] != review.attemptSessionId):
            raise ValueError("Review must match the active saved practice attempt")
        if set(review.answers) != {check["id"] for check in checks_for(practice, ko)}:
            raise ValueError("Answer every saved delivery check exactly once")
        if practice.get("deliveryReview"):
            raise ValueError("This attempt already has a saved review")
        if compare_snapshots(doc["snapshot"], attempt["snapshot"], practice)["outcome"] != "review_required":
            raise ValueError("Insufficient observations for delivery review")
        practice["deliveryReview"] = review.model_dump()
        result = compare_snapshots(doc["snapshot"], attempt["snapshot"], practice)
        practice["comparison"] = result
        message = ("영상에서 직접 확인한 항목별 결과를 저장했어요. " if ko else "Saved your check-by-check review of the recording. ") + next_instruction(practice, ko)
        components.append({"type": "comparison", "comparison": result})
        choices(choice("retry_practice", "같은 기준으로 다시 연습", "Retry with the same checks"),
                choice("choose_next_goal", "다음 목표 선택", "Choose next goal"),
                choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"))
    elif action.startswith("assess_delivery_"):
        if practice and practice.get("rubricVersion"):
            raise ValueError("Use the saved action checklist to assess this practice")
        if (
            not practice
            or not attempt
            or state.stage != "comparison_ready"
            or practice.get("evaluationMode") != "delivery_review"
        ):
            raise ValueError("No delivery review is ready")
        if attempt["snapshot"]["request"][
            "sessionId"
        ] != state.attemptSessionId or state.attemptSessionId != practice.get(
            "attemptSessionId"
        ):
            raise ValueError("Delivery review must use the saved practice attempt")
        result = compare_snapshots(doc["snapshot"], attempt["snapshot"], practice)
        if result["outcome"] == "insufficient_data":
            raise ValueError("Insufficient observations for delivery review")
        assessment = {
            "assess_delivery_achieved": "achieved",
            "assess_delivery_partial": "partial",
            "assess_delivery_retry": "retry_recommended",
        }[action]
        practice["deliveryAssessment"] = assessment
        result = compare_snapshots(doc["snapshot"], attempt["snapshot"], practice)
        practice["comparison"] = result
        focus_finding = next(f for f in findings if f["id"] == practice["findingId"])
        if assessment == "achieved":
            message = (
                f"‘{guidance(focus_finding, ko)['goal']}’를 해냈다고 직접 확인한 결과로 기록했어요. 다음 발표에서도 같은 행동을 유지해 보세요. 원하면 다른 목표를 선택할 수 있습니다."
                if ko
                else f"Saved your confirmation that you carried out '{guidance(focus_finding, ko)['goal']}'. Keep that action next time, or choose another goal."
            )
        else:
            adjustments = {
                "pitch_change": (
                    "다음에는 녹화 전에 핵심 문장 하나를 먼저 소리 내어 정해 보세요. 그 문장 뒤에만 한 번 멈추고, 나머지는 편한 목소리로 이어가세요.",
                    "Before recording, say your chosen key sentence once. Pause after that sentence only, then use your comfortable voice for the rest.",
                ),
                "pitch_variability": (
                    "다음에는 강조할 단어를 하나만 정해 보세요. 같은 문장을 평소처럼 한 번, 그 단어를 강조해 한 번 말하며 비교하세요.",
                    "Choose just one word to emphasize. Say the sentence once naturally and once with that emphasis, then compare.",
                ),
                "gaze": (
                    "다음에는 핵심 문장을 카메라 옆에 짧게 적어 두세요. 그 문장을 말할 때만 카메라를 바라보고 나머지 시선은 자연스럽게 두세요.",
                    "Put a short reminder beside the camera. Look toward it for your key sentence and keep other gaze shifts natural.",
                ),
                "lip_tension": (
                    "다음에는 고른 문장을 조금 짧게 나눠 보세요. 의미 단위 사이에만 멈추고 실제 소리가 더 분명하게 들리는지 확인하세요.",
                    "Break the sentence into shorter meaningful phrases. Pause only between them and listen for clearer speech.",
                ),
                "brow_tension": (
                    "다음에는 전달할 느낌 하나만 먼저 정하세요. 핵심 문장 한 곳에서 그 느낌을 표현하고 영상으로 의도와 맞는지 확인하세요.",
                    "Choose one feeling to convey. Express it for your key sentence, then check the recording against your intention.",
                ),
            }
            adjustment = adjustments.get(
                focus_finding["id"],
                (
                    "같은 목표로 한 번 더 연습하고 두 영상을 비교해 보세요.",
                    "Try the same goal once more and compare both recordings.",
                ),
            )[0 if ko else 1]
            message = (
                "직접 확인한 결과를 기록했어요. " if ko else "Saved your review. "
            ) + adjustment
        components.append({"type": "comparison", "comparison": result})
        choices(
            choice("retry_practice", "같은 연습 다시 하기", "Retry practice"),
            choice("choose_next_goal", "다음 목표 선택", "Choose next goal"),
            choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"),
        )
    elif action == "compare_previous_session":
        if previous:
            # Display chronological previous -> current.
            result = compare_snapshots(previous["snapshot"], doc["snapshot"])
            components.append({"type": "comparison", "comparison": result})
            message = (
                "이전 세션과 이번 세션의 동일 지표를 비교합니다. 기준과 환경이 다르거나 자료가 부족하면 개선 여부를 판단하지 않습니다."
                if ko
                else "Compare the previous and current sessions with identical metrics. Different versions, scenes or insufficient data prevent an improvement judgment."
            )
            goal = previous["state"].get("nextGoalId") or previous["state"].get(
                "selectedFindingId"
            )
            prior_finding = next(
                (
                    f
                    for f in previous["snapshot"]["report"]["priorities"]
                    if f["id"] == goal
                ),
                None,
            )
            if prior_finding:
                message += (" 이전 목표: " if ko else " Previous goal: ") + label(
                    prior_finding, ko
                )
            prior_result = next(
                (
                    p.get("comparison")
                    for p in reversed(previous["practices"])
                    if p.get("comparison")
                ),
                None,
            )
            if prior_result:
                outcomes = {
                    "achieved": ("달성", "Achieved"),
                    "partial": ("부분 달성", "Partial"),
                    "retry_recommended": ("재시도 권장", "Retry recommended"),
                    "insufficient_data": ("자료 부족", "Insufficient data"),
                    "review_required": ("영상 확인 대기", "Awaiting delivery review"),
                }
                message += (
                    " · 이전 연습 결과: " if ko else " · Previous practice result: "
                ) + outcomes.get(
                    prior_result["outcome"], ("자료 부족", "Insufficient data")
                )[0 if ko else 1]
        else:
            message = (
                "비교할 이전 세션의 원본 분석 자료가 없습니다."
                if ko
                else "No previous session with raw observations is available."
            )
    elif action == "choose_next_goal":
        if state.stage in {"recording", "evaluating"}:
            raise ValueError("Finish evaluation before choosing the next goal")
        state.stage = "next_goal"
        if request.findingId:
            state.nextGoalId = request.findingId
        message = (
            "다음 발표에서 확인할 목표를 하나 선택하세요."
            if ko
            else "Choose one goal to review next session."
        )
        if request.findingId and finding:
            message = (
                f"다음 목표로 ‘{guidance(finding, ko)['goal']}’ 항목을 선택했습니다. 목표를 저장하고 마칠 수 있습니다."
                if ko
                else f"Selected {guidance(finding, ko)['goal']} as the next goal. Save it to finish."
            )

        if state.reviewFeedback == "intentional" and not any(
            f["id"] != state.selectedFindingId for f in findings
        ):
            message = (
                "추가로 확인할 근거 있는 항목이 없습니다. 의도한 표현을 유지하며 이번 코칭을 마쳐도 좋습니다."
                if ko
                else "No additional supported focus is available. Keep your intentional expression and finish this review when ready."
            )
        choices(
            *[
                choice(
                    "choose_next_goal",
                    guidance(f, ko)["goal"],
                    guidance(f, ko)["goal"],
                    f["id"],
                )
                for f in findings
                if not (
                    state.reviewFeedback == "intentional"
                    and f["id"] == state.selectedFindingId
                )
            ],
            choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"),
        )
    elif action == "finish_coaching":
        if state.stage in {"recording", "evaluating"}:
            raise ValueError("Finish evaluation before completing coaching")
        state.nextGoalId = state.nextGoalId or (
            state.selectedFindingId if state.reviewFeedback != "intentional" else None
        )
        state.stage = "completed"
        message = (
            (
                "코칭 결과와 다음 목표를 저장했습니다."
                if state.nextGoalId
                else "코칭 결과를 저장했습니다. 의도한 표현은 다음 발표에서도 유지해 보세요."
            )
            if ko
            else (
                "Saved coaching results and the next goal."
                if state.nextGoalId
                else "Saved the coaching review. Keep your intended expression next time."
            )
        )
    else:
        message = (
            "저장된 자료로 그 질문에 답할 수 없습니다. 구간, 측정값, 이전 세션 또는 연습에 대해 질문해 주세요."
            if ko
            else "The saved data cannot answer that question. Ask about intervals, measurements, previous sessions or practice."
        )
        choices(choice("review", "보고서 살펴보기", "Review report"))
    if not any(c["type"] == "action_choices" for c in components):
        if state.stage == "recording":
            choices(
                choice("finish_recording", "녹화 종료 및 분석", "Finish and analyze")
            )
        elif state.stage == "evaluating":
            choices(choice("compare_attempts", "분석 결과 확인", "Check analysis"))
        elif state.stage == "practice_created":
            choices(
                choice(
                    "start_recording", "재연습 녹화 시작", "Start practice recording"
                )
            )
        elif state.stage == "comparison_ready":
            choices(
                choice("retry_practice", "같은 연습 다시 하기", "Retry practice"),
                choice("choose_next_goal", "다음 목표 선택", "Choose next goal"),
                choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"),
            )
        elif state.stage not in {"completed", "next_goal"}:
            choices(
                choice("review", "보고서 살펴보기", "Review report"),
                choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"),
            )
    state.lastAction = request.action
    doc["state"] = state.model_dump()
    doc["revision"] += 1
    raw = {
        "message": message,
        "components": components,
        "conversationState": doc["state"],
        "revision": doc["revision"],
    }
    # Previous comparison uses chronological ordering in its validation too.
    response = validate_response(raw, doc, attempt=attempt, previous=previous)
    action_labels = {
        "submit_practice_review": ("연습 항목별 확인", "Review practice checks"),
        "confirm_intent": ("의도한 표현이었어요", "That was intentional"),
        "guide_review": ("영상 확인 방법", "Help reviewing the video"),
        "explain_score": ("스트레스 신호 점수 설명", "Explain stress signal score"),
        "assess_delivery_achieved": (
            "의도한 전달 달성",
            "Delivery matched my intention",
        ),
        "assess_delivery_partial": (
            "전달 일부 달성",
            "Delivery partly matched my intention",
        ),
        "assess_delivery_retry": ("전달 재시도", "Retry delivery"),
        "review": ("보고서 살펴보기", "Review report"),
        "explain_finding": ("선정 이유 보기", "Explain finding"),
        "show_measurements": ("측정값 보기", "Show measurements"),
        "jump_to_video": ("영상 보기", "Review video"),
        "create_practice": ("연습 과제 만들기", "Create practice"),
        "start_recording": ("녹화 시작", "Start recording"),
        "finish_recording": ("녹화 종료와 분석", "Finish and analyze"),
        "compare_attempts": ("재촬영 비교", "Compare takes"),
        "retry_practice": ("같은 연습 재시도", "Retry practice"),
        "choose_next_goal": ("다음 목표 선택", "Choose next goal"),
        "compare_previous_session": ("이전 세션 비교", "Compare previous session"),
        "finish_coaching": ("목표 저장하고 마치기", "Save and finish"),
    }
    doc["messages"] = (
        doc["messages"]
        + [
            {
                "role": "user",
                "text": request.message
                or action_labels.get(
                    request.action, ("보고서 질문", "Report question")
                )[0 if ko else 1],
            },
            {"role": "agent", "text": message, "response": response},
        ]
    )[-40:]
    return doc, response


def _matches_language(text, language):
    return bool(text) and bool(re.search(r"[가-힣]", text)) == (language == "ko")


def respond(doc, request: CoachRequest, *, attempt=None, previous=None, route=None):
    """Render both locales from the same verified action; persist one state change.

    The intent router runs once. Alternate rendering is pure and never saves a
    second exercise, revision or action. Component identities use the committed
    response, so changing language cannot create a new practice.
    """
    doc, request = prepare_review_request(doc, request)
    routed = []

    def cached_route(context):
        if not routed:
            routed.append(route(context))
        return routed[0]

    router = cached_route if route else None
    updated, response = _respond(
        doc, request, attempt=attempt, previous=previous, route=router
    )
    other_language = "en" if request.language == "ko" else "ko"
    alternate, translated = _respond(
        doc,
        request.model_copy(update={"language": other_language}),
        attempt=attempt,
        previous=previous,
        route=router,
    )
    translated["conversationState"] = deepcopy(response["conversationState"])
    for component, committed in zip(translated["components"], response["components"]):
        if component["type"] == "practice":
            component["practiceId"] = committed["practiceId"]
    for component in translated["components"]:
        if component["type"] == "practice" and request.action == "create_practice":
            practice = next(
                p for p in updated["practices"] if p["id"] == component["practiceId"]
            )
            keys = ("label", "instruction", "criterion", "durationSeconds", "successChecks")
            practice["translations"] = {
                request.language: {k: practice[k] for k in keys},
                other_language: {k: component[k] for k in keys},
            }
    validate_response(translated, updated, attempt=attempt, previous=previous)
    for offset in (-2, -1):
        primary, secondary = updated["messages"][offset], alternate["messages"][offset]
        primary["language"] = request.language
        primary["translations"] = {
            request.language: {
                k: deepcopy(v) for k, v in primary.items() if k in {"text", "response"}
            },
            other_language: (
                {"text": translated["message"], "response": translated}
                if offset == -1
                else {"text": secondary["text"]}
            ),
        }
    return updated, response


def localized_messages(doc, language):
    """Return saved conversation in the UI locale without mutating state."""
    messages = []
    for original in doc["messages"]:
        message = {
            k: deepcopy(v)
            for k, v in original.items()
            if k not in {"translations", "language"}
        }
        translated = original.get("translations", {}).get(language)
        if translated:
            message.update(deepcopy(translated))
        elif message["role"] == "agent" and not _matches_language(
            message["text"], language
        ):
            # Legacy prose has no translation. Preserve data without guessing a translation.
            message["text"] = (
                "이 답변은 다른 언어로 저장되었습니다. 현재 언어로 이어서 질문해 주세요."
                if language == "ko"
                else "This reply was saved in another language. Continue in the current language."
            )
            message.pop("response", None)
        if message.get("response"):
            from .finding_evidence import attach_observation_videos

            message["response"] = attach_observation_videos(
                message["response"], doc, language == "ko"
            )
        messages.append(message)
    if messages and messages[-1].get("response"):
        messages[-1]["response"] = attach_coaching_path(
            messages[-1]["response"], doc, language == "ko"
        )
        if doc["state"].get(
            "reviewFeedback"
        ) == "intentional" and REASK_INTENTION.search(messages[-1]["text"]):
            messages[-1]["supersededQuestion"] = True
    return messages
