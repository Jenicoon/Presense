"""Actionable review paths; proposed exercises, never inferred delivery diagnoses."""

import re
import json
from pathlib import Path
from copy import deepcopy
from typing import Literal

ReviewOutcome = Literal[
    "intentional",
    "effective",
    "needs_contrast",
    "needs_phrasing",
    "unclear_speech",
    "expression_mismatch",
    "gaze_distracting",
    "unsure",
    "needs_face_reset",
]
PracticeStrategy = Literal[
    "contrast", "phrasing", "two_versions", "clear_phrases", "expression", "gaze_anchor", "face_reset"
]

REASK_INTENTION = re.compile(
    r"의도.{0,22}(?:였는지|인지|인가요|맞는지|확인(?:해\s*(?:보|주세)|하(?:세|시)))|(?:check|review|see|whether|ask).{0,45}intentional|was.{0,18}intentional\?",
    re.IGNORECASE,
)

METHODS = {
    "contrast": {
        "label": ("핵심 문장 대비 연습", "Key sentence contrast"),
        "goal": (
            "전달할 문장 하나만 고르고 그 문장에만 강조를 주기",
            "Choose one key sentence and emphasize only that sentence",
        ),
        "check": (
            "녹음을 듣고 고른 문장이 나머지 문장과 구분되는지 직접 확인하기",
            "Listen back and check whether your chosen sentence stands out from the others",
        ),
    },
    "phrasing": {
        "label": ("문장 경계 연습", "Sentence boundary practice"),
        "goal": (
            "의미가 끝나는 곳에만 쉼을 두고 다음 문장을 새로 시작하기",
            "Pause at a completed thought and start the next sentence as a new unit",
        ),
        "check": (
            "내용을 아는 사람만이 아니라 처음 듣는 사람도 문장 끝을 구분할 수 있을지 직접 듣기",
            "Listen for whether a first-time listener could distinguish where each sentence ends",
        ),
    },
    "two_versions": {
        "label": ("두 방식으로 말하고 비교하기", "Compare two delivery versions"),
        "goal": (
            "같은 문장을 평소 방식과 다른 강조 또는 쉼으로 말해 비교하기",
            "Say the same sentence naturally, then with a different emphasis or pause",
        ),
        "check": (
            "두 녹음 중 전달하려던 뜻이 더 잘 드러나는 방식을 직접 선택하기",
            "Choose the version that better expresses your intended meaning",
        ),
    },
    "clear_phrases": {
        "label": ("짧은 의미 단위로 말하기", "Speak in short meaningful phrases"),
        "goal": (
            "직접 고른 문장을 짧은 의미 단위로 나눠 다시 말하기",
            "Divide a self-selected sentence into short meaningful phrases",
        ),
        "check": (
            "자연스러운 목소리를 유지하면서 단어가 빠지지 않고 들리는지 직접 확인하기",
            "Listen for complete, audible words while keeping your voice comfortable",
        ),
    },
    "expression": {
        "label": ("메시지와 표정 맞추기", "Match expression to the message"),
        "goal": (
            "전달할 느낌을 직접 정하고 같은 문장을 두 표정으로 말해 비교하기",
            "Choose an intended feeling and compare two expressions for the same sentence",
        ),
        "check": (
            "직접 정한 느낌과 표정이 맞는지 소리와 함께 확인하기",
            "Watch with sound to check expression against the feeling you selected",
        ),
    },
    "gaze_anchor": {
        "label": ("핵심 문장에서 시선 두기", "Anchor gaze for the key sentence"),
        "goal": (
            "핵심 문장을 말할 때만 카메라 부근을 보고 나머지는 자연스럽게 두기",
            "Look near the camera for the key sentence and keep other gaze shifts natural",
        ),
        "check": (
            "핵심 문장 동안 시선이 머물렀는지 영상을 보고 확인하기",
            "Watch whether your gaze stayed near the camera during the key sentence",
        ),
    },
}
PROFILES = {
    "pitch_change": {
        "check": (
            "높낮이가 바뀌는 순간에 중요한 문장이 구분되는지 들어보세요. 문장 끝의 쉼과 다음 문장 시작도 따로 들어보세요.",
            "Listen for whether a pitch change marks a key sentence. Separately check the pause at a sentence ending and the next sentence start.",
        ),
        "outcomes": [
            ("effective", "핵심 문장이 잘 구분돼요", "The key sentence stands out"),
            ("needs_contrast", "무엇을 강조하는지 애매해요", "The emphasis is unclear"),
            (
                "needs_phrasing",
                "문장 경계가 잘 안 들려요",
                "Sentence boundaries are unclear",
            ),
            ("unsure", "두 방식으로 연습해 보고 싶어요", "Try two versions first"),
        ],
        "strategies": ["contrast", "phrasing", "two_versions"],
    },
    "pitch_variability": {
        "check": (
            "고른 구간을 듣고 가장 중요한 문장 하나를 직접 골라보세요. 그 문장이 나머지와 구분되는지, 의미가 끝나기 전에 끊겨 들리는지 확인하세요.",
            "Listen to one interval and choose its key sentence yourself. Check whether it stands out and whether the thought sounds interrupted before it is complete.",
        ),
        "outcomes": [
            ("effective", "핵심 문장이 잘 구분돼요", "The key sentence stands out"),
            (
                "needs_contrast",
                "강조할 부분이 잘 안 들려요",
                "The emphasis does not stand out",
            ),
            (
                "needs_phrasing",
                "문장 끝과 다음 문장이 붙어 들려요",
                "Sentences run together",
            ),
            ("unsure", "두 방식으로 연습해 보고 싶어요", "Try two versions first"),
        ],
        "strategies": ["contrast", "phrasing", "two_versions"],
    },
    "lip_tension": {
        "check": (
            "입 모양만으로 발음이 좋거나 나쁜지는 알 수 없어요. 이 장면을 소리와 함께 재생해 보세요. 잘 들리면 지금 방식을 유지하고, 다시 듣게 된 문장이 있다면 그 문장만 짧게 나눠 연습해요.",
            "Mouth opening alone cannot tell us whether pronunciation is clear. Play this interval with sound. Keep your delivery if it is clear; if you need to replay a sentence, rehearse that sentence in short phrases.",
        ),
        "outcomes": [
            ("effective", "실제 소리는 잘 들려요", "The speech is audible"),
            (
                "unclear_speech",
                "다시 듣게 된 문장이 있어요",
                "I needed to replay a sentence",
            ),
            ("unsure", "두 방식으로 비교해 볼게요", "Compare two versions"),
        ],
        "strategies": ["clear_phrases", "two_versions"],
    },
    "brow_tension": {
        "check": (
            "같은 구간을 소리 없이 한 번, 소리와 함께 한 번 보세요. 전달하려던 느낌을 직접 고른 뒤 표정이 그 느낌과 맞는지 판단하세요.",
            "Watch once without sound, then with sound. Choose the intended feeling yourself and check whether the expression matches it.",
        ),
        "outcomes": [
            (
                "effective",
                "표정이 메시지와 잘 맞아요",
                "Expression matches the message",
            ),
            (
                "expression_mismatch",
                "표현하려던 느낌과 달라요",
                "Expression differs from my intention",
            ),
            ("unsure", "두 표정으로 비교해 볼게요", "Compare two expressions"),
        ],
        "strategies": ["expression"],
    },
    "gaze": {
        "check": (
            "핵심 문장을 말할 때 카메라 부근에 시선이 머무는지 보세요. 시선 이동이 방해되는지는 영상과 전달 의도를 함께 보고 직접 판단하세요.",
            "Watch where the gaze rests during the key sentence. Judge distracting shifts yourself against the recording and intended delivery.",
        ),
        "outcomes": [
            ("effective", "시선 이동이 자연스러워요", "Gaze shifts feel natural"),
            (
                "gaze_distracting",
                "핵심 문장에서 시선이 자주 옮겨가요",
                "Gaze shifts during the key sentence",
            ),
            ("unsure", "시선 두는 연습을 해볼게요", "Try a gaze anchor"),
        ],
        "strategies": ["gaze_anchor"],
    },
}
V2_GUIDANCE = json.loads((Path(__file__).resolve().parents[1]/"shared/concept-v2-guidance.json").read_text())
METHODS["face_reset"] = {
    "label": ("눈 주변 움직임과 시선 비교하기", "Compare eye-area movement and gaze"),
    "goal": ("같은 문장을 렌즈나 청중 위치를 보며 다시 말하기", "Repeat the same sentence while looking toward the lens or an audience position"),
    "check": ("같은 조명과 카메라 위치에서 의도하지 않은 조임이 반복되는지 원본과 비교하기", "With matching lighting and camera position, compare whether unintended tightening repeats"),
}
for identity, view in V2_GUIDANCE.items():
    base = view["profile"]
    if base in PROFILES:
        outcomes = list(PROFILES[base]["outcomes"])
    elif base == "eye_reset":
        outcomes = [("effective", "지금 표현이 의도와 맞아요", "This expression matches my intention"), ("needs_face_reset", "시선을 정해 다시 비교해볼게요", "Repeat with a chosen gaze point")]
    else:
        outcomes = [("effective", "지금 전달이 편하게 들려요", "The delivery sounds comfortable"), ("needs_phrasing", "문장 사이에 쉼이 필요해요", "I need pauses between thoughts"), ("unsure", "두 방식으로 비교해 볼게요", "Compare two versions")]
    PROFILES[identity] = {"check":tuple(view["check"]), "outcomes":outcomes, "strategies":view["strategies"]}

OUTCOME_METHOD = {
    "needs_face_reset": "face_reset",
    "needs_contrast": "contrast",
    "needs_phrasing": "phrasing",
    "unclear_speech": "clear_phrases",
    "expression_mismatch": "expression",
    "gaze_distracting": "gaze_anchor",
    "unsure": "two_versions",
}


def profile(finding):
    return PROFILES.get(
        finding["id"],
        {
            "check": (
                "실제 영상에서 직접 바꿔 보고 싶은 행동 하나를 고르세요.",
                "Choose one delivery action from the actual recording.",
            ),
            "outcomes": [
                ("effective", "지금 전달을 유지할게요", "Keep this delivery"),
                ("unsure", "두 방식으로 비교해 볼게요", "Compare two versions"),
            ],
            "strategies": ["two_versions"],
        },
    )


def selected_finding(doc, finding_id=None):
    findings = doc["snapshot"]["report"]["priorities"]
    identity = finding_id or doc["state"].get("selectedFindingId")
    return next(
        (f for f in findings if f["id"] == identity), next(iter(findings), None)
    )


def prepare_review_request(doc, request):
    doc = deepcopy(doc)
    if doc["state"].get("reviewFeedback") == "intentional" and not doc["state"].get(
        "reviewOutcome"
    ):
        doc["state"]["reviewOutcome"] = "intentional"
    finding = selected_finding(doc, request.findingId)
    if (
        request.findingId
        and finding
        and doc["state"].get("selectedFindingId") != request.findingId
    ):
        if doc["state"]["stage"] in {"recording", "evaluating"}:
            raise ValueError("Finish the active recording before switching focus")
        doc["state"].update(
            selectedFindingId=finding["id"],
            reviewFeedback=None,
            reviewOutcome=None,
            practiceStrategyId=None,
            activePracticeId=None,
            attemptSessionId=None,
            stage="finding_selected",
        )
    if request.action == "submit_review":
        if not finding or doc["state"]["stage"] not in {
            "session_review",
            "finding_selected",
            "next_goal",
        }:
            raise ValueError("No finding is awaiting a review result")
        allowed = {row[0] for row in profile(finding)["outcomes"]}
        if request.reviewOutcome not in allowed:
            raise ValueError("Review outcome does not match this finding")
        doc["state"]["selectedFindingId"] = finding["id"]
        doc["state"]["reviewOutcome"] = request.reviewOutcome
        strategy = OUTCOME_METHOD.get(request.reviewOutcome)
        if strategy not in profile(finding)["strategies"]:
            strategy = profile(finding)["strategies"][0]
        doc["state"]["practiceStrategyId"] = strategy
        doc["state"]["reviewFeedback"] = (
            "intentional"
            if request.reviewOutcome == "effective"
            else "unsure"
            if request.reviewOutcome == "unsure"
            else "needs_practice"
        )
        request = request.model_copy(
            update={
                "action": "confirm_intent"
                if request.reviewOutcome == "effective"
                else "create_practice",
                "findingId": finding["id"],
                "reviewOutcome": None,
                "practiceStrategyId": None,
            }
        )
    elif request.action == "confirm_intent":
        if doc["state"].get("reviewOutcome") not in {"effective", "intentional"}:
            doc["state"]["reviewOutcome"] = "intentional"
    if request.practiceStrategyId:
        if (
            request.action != "create_practice"
            or not finding
            or request.practiceStrategyId not in profile(finding)["strategies"]
        ):
            raise ValueError("Practice strategy does not match this finding")
        doc["state"]["practiceStrategyId"] = request.practiceStrategyId
    return doc, request


def review_choices(finding, ko):
    return [
        {
            "id": "review_" + outcome,
            "label": korean if ko else english,
            "action": "submit_review",
            "findingId": finding["id"],
            "reviewOutcome": outcome,
        }
        for outcome, korean, english in profile(finding)["outcomes"]
    ]


def method_choices(finding, ko):
    return [
        {
            "id": "practice_" + strategy,
            "label": METHODS[strategy]["label"][0 if ko else 1],
            "action": "create_practice",
            "findingId": finding["id"],
            "practiceStrategyId": strategy,
        }
        for strategy in profile(finding)["strategies"]
    ]


def attach_coaching_path(response, doc, ko):
    """Progress controls are state-owned; a model cannot remove the next step."""
    response = deepcopy(response)
    state = response["conversationState"]
    finding = selected_finding(doc, state.get("selectedFindingId"))
    if not finding or state["stage"] not in {"session_review", "finding_selected"}:
        return response
    effective = (
        state.get("reviewOutcome") in {"effective", "intentional"}
        or state.get("reviewFeedback") == "intentional"
    )
    components = response["components"]
    others = [
        c
        for c in components
        if c["type"] != "action_choices" and c["type"] != "coaching_path"
    ]
    if effective:
        body = (
            (
                "직접 확인한 전달을 다음 발표에서도 유지하세요. 더 연습하고 싶으면 아래 방법 하나를 골라 같은 내용을 다시 말해보세요."
                if state.get("reviewOutcome") == "effective"
                else "의도한 표현이라는 답을 기록했습니다. 이 변화 자체를 고칠 필요는 없습니다. 더 연습하고 싶으면 아래 방법 하나를 골라 같은 내용을 다시 말해보세요."
            )
            if ko
            else (
                "Keep the delivery you confirmed. For an optional rehearsal, choose one method below and repeat the same content."
                if state.get("reviewOutcome") == "effective"
                else "Recorded your answer that this was intentional. The change itself needs no correction. For an optional rehearsal, choose one method below and repeat the same content."
            )
        )
        title = "확인 완료 · 다음에 할 일" if ko else "Review complete · next action"
        choices = method_choices(finding, ko) + [
            {
                "id": "next_goal",
                "label": "다른 항목으로 이동" if ko else "Review another focus",
                "action": "choose_next_goal",
            },
            {
                "id": "finish",
                "label": "이 표현 유지하고 마치기"
                if ko
                else "Keep this delivery and finish",
                "action": "finish_coaching",
            },
        ]
    else:
        body = profile(finding)["check"][0 if ko else 1]
        title = (
            "확인한 뒤 아래에서 결과를 선택하세요"
            if ko
            else "After reviewing, choose what you noticed"
        )
        choices = review_choices(finding, ko)
    if not any(component["type"] == "review_guide" and component.get("findingId") == finding["id"] for component in others):
        others.insert(0, {"type": "coaching_path", "findingId": finding["id"], "title": title, "instruction": body})
    response["components"] = others + [{"type": "action_choices", "choices": choices}]
    return response
