"""Grounded coaching actions. Text is rendered from verified data, never executable LLM output.

The LLM may route a free-text question to an allowlisted intent. It cannot supply
measurements, component payloads, exercises, citations or state transitions.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field

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


class ConversationState(Contract):
    sessionId: str
    selectedFindingId: str | None = None
    activePracticeId: str | None = None
    attemptSessionId: str | None = None
    stage: Stage = "session_review"
    nextGoalId: str | None = None
    lastAction: Action | None = None


class Choice(Contract):
    id: str
    label: str
    action: Action
    findingId: str | None = None


class Choices(Contract):
    type: Literal["action_choices"]
    choices: list[Choice] = Field(max_length=10)


class SegmentCard(Contract):
    type: Literal["video_segment"]
    sessionId: str
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


class ComparisonCard(Contract):
    type: Literal["comparison"]
    comparison: dict


class Notice(Contract):
    type: Literal["insufficient_data"]
    label: str


Component = Annotated[
    Choices | SegmentCard | FindingCard | PracticeCard | ComparisonCard | Notice,
    Field(discriminator="type"),
]


class CoachResponse(Contract):
    message: str
    components: list[Component] = Field(max_length=16)
    conversationState: ConversationState
    revision: int


def new_document(request: ReviewRequest, report: dict, version: str) -> dict:
    return {
        "snapshot": {
            "request": request.model_dump(),
            "report": report,
            "modelVersion": version,
            "metricDefinitionVersion": report.get("agentMemory", {}).get(
                "metricDefinitionVersion", "session-analysis-v4"
            ),
        },
        "state": ConversationState(sessionId=request.sessionId).model_dump(),
        "practices": [],
        "messages": [],
        "revision": 0,
    }


def measurement_name(key, ko):
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
    if (
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
    return {
        "previousSessionId": before["request"]["sessionId"],
        "currentSessionId": after["request"]["sessionId"],
        "outcome": outcome,
        "compatible": compatible,
        "scope": "practice" if practice else "previous_session",
        "before": a,
        "after": b,
        "modelScoreChange": round(b["value"] - a["value"], 6) if sufficient else None,
        "measurements": changes if compatible else [],
        "referenceValue": reference,
        "criterion": "relative_deviation_reduction_20pct"
        if practice
        else "same_metric_descriptive_comparison",
        "formula": "1 - |current - reference| / |previous - reference|; ≥ 0.20 achieved, > 0 partial, otherwise retry",
        "note": "Selected measurement goal only; a lower model score or pitch does not prove better delivery.",
    }


def validate_response(raw, doc, attempt=None, previous=None):
    response = CoachResponse.model_validate(raw)
    state = response.conversationState
    if state.sessionId != doc["state"]["sessionId"]:
        raise ValueError("Cross-session state")
    findings = {f["id"] for f in doc["snapshot"]["report"]["priorities"]}
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
        elif isinstance(component, FindingCard) and component.findingId not in findings:
            raise ValueError("Unknown finding")
        elif isinstance(component, PracticeCard):
            p = practices.get(component.practiceId)
            content = {
                k: getattr(component, k)
                for k in ("label", "instruction", "criterion", "durationSeconds")
            }
            allowed = (
                (
                    [{k: p[k] for k in content}]
                    + list(p.get("translations", {}).values())
                )
                if p
                else []
            )
            if content not in allowed:
                raise ValueError("Unknown or altered exercise")
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
    }
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

    def segment(snap, row):
        components.append(
            {
                "type": "video_segment",
                "sessionId": snap["request"]["sessionId"],
                "startMs": row["startMs"],
                "endMs": row["endMs"],
                "label": "이 구간 확인하기" if ko else "Review this interval",
            }
        )

    practice = next(
        (p for p in doc["practices"] if p["id"] == state.activePracticeId), None
    )
    message = ""
    if action == "review":
        from .report_agent import _observation_text

        report = doc["snapshot"]["report"]
        saved = report["summaryText"]
        message = (
            saved
            if _matches_language(saved, request.language)
            else (_observation_text(findings[0], ko) if findings else "")
        )
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
                    {"type": "finding", "findingId": f["id"], "label": label(f, ko)}
                )
            choices(
                choice(
                    "explain_finding",
                    "선정 이유와 영상 보기",
                    "Reason and video",
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
            from .report_agent import _observation_text

            message = _observation_text(finding, ko)
            message += (
                f" 겹치지 않는 관측 {finding.get('independentObservations', 0)}개에서 확인했습니다. 점수와 측정값만으로 원인을 단정할 수 없습니다. 영상에서 의도한 강조와 실제 전달을 확인하세요."
                if ko
                else f" Supported by {finding.get('independentObservations', 0)} non-overlapping observations. Scores and measurements cannot establish a cause. Check intended emphasis and delivery in the video."
            )
            rows = [
                s
                for s in doc["snapshot"]["request"]["segments"]
                if s["segmentId"] in {o["segmentId"] for o in finding["observations"]}
            ]
            for row in rows[:3]:
                segment(doc["snapshot"], row)
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
                choice("show_measurements", "관련 측정값 보기", "Show measurements"),
                choice("create_practice", "이 부분 연습하기", "Practice this interval"),
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
            specific = {
                "pitch_change": (
                    "선택 구간을 듣고 의도한 강조였는지 확인하세요. 같은 내용을 30초 다시 말하며 강조할 문장 하나를 직접 정해 보세요.",
                    "Listen for intended emphasis in the selected interval. Repeat the same content for 30 seconds, choosing one sentence to emphasize.",
                ),
                "pitch_variability": (
                    "선택 구간의 억양을 들어보세요. 같은 문장을 다른 강조로 30초 반복하고 어느 쪽이 의도에 맞는지 직접 비교하세요.",
                    "Listen to the intonation. Repeat the same sentences for 30 seconds with different emphasis, and compare with your intention.",
                ),
                "brow_tension": (
                    "영상에서 표정 변화가 전달 의도와 맞는지 확인하세요. 의도한 표정을 정하고 같은 내용을 30초 다시 발표하세요. 특정 표정을 강제로 줄일 필요는 없습니다.",
                    "Review whether facial movement matches your intention. Repeat the same content for 30 seconds with your intended expression; no forced facial correction is needed.",
                ),
                "lip_tension": (
                    "입 움직임과 실제 발화를 영상에서 함께 확인하세요. 전달이 흐린 지점을 직접 골라 같은 내용을 30초 다시 발표하세요.",
                    "Review mouth movement alongside recorded speech. Choose any unclear delivery yourself and repeat the same content for 30 seconds.",
                ),
                "gaze": (
                    "영상에서 의도한 시선 이동과 화면 기준 시선 추정치를 함께 확인하세요. 같은 카메라 위치에서 같은 내용을 30초 다시 발표하세요.",
                    "Review intended gaze shifts alongside the camera estimate. Repeat the same content for 30 seconds with the same camera placement.",
                ),
            }
            if finding["id"] in specific:
                practice["instruction"] = specific[finding["id"]][0 if ko else 1]
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
            practice = deepcopy(practice)
            practice["id"] = str(uuid4())
            practice.pop("comparison", None)
            practice.pop("attemptSessionId", None)
            doc["practices"].append(practice)
            state.activePracticeId = practice["id"]
        state.stage = "recording"
        state.attemptSessionId = None
        message = (
            "카메라와 마이크를 확인한 후 준비 화면에서 시작하세요. 같은 환경과 내용으로 30초 이상 발표하고 종료해 주세요."
            if ko
            else "Check the camera and microphone, then start on the preparation screen. Use the same scene and content for at least 30 seconds, then finish."
        )
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
            message = (
                "같은 지표로 이전 시도와 재촬영을 비교했습니다. 수치 변화는 발표 실력이나 감정을 확정하지 않습니다."
                if ko
                else "Compared both takes using the same metrics. Changes do not establish delivery quality or emotion."
            )
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
                f"다음 목표로 ‘{label(finding, ko)}’ 항목을 선택했습니다. 목표를 저장하고 마칠 수 있습니다."
                if ko
                else f"Selected {label(finding, ko)} as the next goal. Save it to finish."
            )

        choices(
            *[
                choice("choose_next_goal", label(f, ko), label(f, ko), f["id"])
                for f in findings
            ],
            choice("finish_coaching", "목표 저장하고 마치기", "Save and finish"),
        )
    elif action == "finish_coaching":
        if state.stage in {"recording", "evaluating"}:
            raise ValueError("Finish evaluation before completing coaching")
        state.nextGoalId = state.nextGoalId or state.selectedFindingId
        state.stage = "completed"
        message = (
            "코칭 결과와 다음 목표를 저장했습니다."
            if ko
            else "Saved coaching results and the next goal."
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
        if component["type"] == "practice":
            practice = next(
                p for p in updated["practices"] if p["id"] == component["practiceId"]
            )
            keys = ("label", "instruction", "criterion", "durationSeconds")
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
        messages.append(message)
    return messages
