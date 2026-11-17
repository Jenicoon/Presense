"""Observable delivery checks; the presenter supplies evidence, the server grades it."""
from typing import Literal
from pydantic import Field
from .report_schema import Contract

Answer = Literal["yes", "partly", "no", "unavailable"]
Condition = Literal["same", "changed", "unknown"]
VERSION = "delivery-action-v1"

class DeliveryReview(Contract):
    practiceId: str = Field(min_length=1, max_length=100)
    attemptSessionId: str = Field(min_length=1, max_length=100)
    sameContent: Condition
    sameEnvironment: Condition
    answers: dict[str, Answer] = Field(min_length=2, max_length=3)

# A strategy selects actions to rehearse, never a diagnosis or an ideal sensor value.
CHECKS = {
    "contrast": [
        ("key_sentence", "고른 핵심 문장 한 곳에만 강조를 주었나요?", "Did you emphasize only your chosen key sentence?"),
        ("contrast", "다시 들었을 때 그 문장이 주변 문장과 구분됐나요?", "On playback, did that sentence stand out from the surrounding sentences?"),
    ],
    "phrasing": [
        ("thought_boundary", "의미가 끝나는 곳에서 잠깐 멈췄나요?", "Did you pause at the end of a completed thought?"),
        ("new_sentence", "다음 문장의 시작이 앞 문장과 구분되어 들렸나요?", "Could you hear the next sentence start as a separate thought?"),
    ],
    "two_versions": [
        ("two_versions", "같은 문장을 강조나 쉼을 달리해 두 번 말했나요?", "Did you say the same sentence twice with a different emphasis or pause?"),
        ("chosen_version", "두 방식을 듣고 전달 의도에 맞는 쪽을 골랐나요?", "Did you listen to both versions and choose the one that fits your intention?"),
    ],
    "clear_phrases": [
        ("meaningful_phrases", "고른 문장을 짧은 의미 단위로 나누어 말했나요?", "Did you say your chosen sentence in short meaningful phrases?"),
        ("audible_words", "다시 들었을 때 고른 문장의 단어가 빠짐없이 들렸나요?", "On playback, could you hear all the words in your chosen sentence?"),
    ],
    "expression": [
        ("two_expressions", "전달할 느낌을 정하고 같은 문장을 두 표정으로 말했나요?", "Did you choose a feeling and try two expressions for the same sentence?"),
        ("message_match", "다시 보며 고른 느낌에 맞는 표정을 선택했나요?", "On playback, did you choose the expression that fits your intended feeling?"),
    ],
    "gaze_anchor": [
        ("key_gaze", "핵심 문장을 말할 때 카메라 부근을 바라봤나요?", "Did you look near the camera for your key sentence?"),
        ("comfortable_gaze", "나머지 문장은 시선을 억지로 고정하지 않고 편하게 말했나요?", "Did you keep your gaze comfortable for the remaining sentences?"),
    ],
    "face_reset": [
        ("brief_break", "렌즈나 청중 위치를 보며 같은 문장을 다시 말했나요?", "Did you repeat the same sentence while looking toward the lens or an audience position?"),
        ("comfortable_repeat", "같은 조명과 카메라 위치에서 의도하지 않은 조임이 반복되는지 비교했나요?", "With matching lighting and camera position, did you compare whether unintended tightening repeated?"),
    ],
}


def checks_for(practice, ko):
    return [{"id": check["id"], "label": check["ko" if ko else "en"]}
            for check in check_catalog(practice)]


def check_catalog(practice):
    return practice.get("reviewChecks") or [{"id": identity, "ko": korean, "en": english}
            for identity, korean, english in CHECKS[practice["strategyId"]]]


def review_outcome(review):
    if review["sameContent"] != "same" or review["sameEnvironment"] != "same":
        return "insufficient_data"
    answers = list(review["answers"].values())
    if "unavailable" in answers:
        return "insufficient_data"
    if all(answer == "yes" for answer in answers):
        return "achieved"
    return "partial" if any(answer in {"yes", "partly"} for answer in answers) else "retry_recommended"


RETRIES = {
    "key_sentence": ("강조할 문장 하나를 먼저 정하고 그 문장에서만 중요한 단어를 또렷하게 말해 보세요.", "Choose one key sentence first and emphasize an important word only in that sentence."),
    "contrast": ("주변 문장은 편한 목소리로 이어가고, 핵심 문장 앞에서 잠깐 멈춰 구분해 보세요.", "Keep surrounding sentences comfortable and pause briefly before the key sentence to distinguish it."),
    "thought_boundary": ("고른 문장에서 의미가 끝나는 곳을 표시하고 그곳에서만 한 번 멈춰 보세요.", "Mark where a thought ends in your chosen sentence and pause there once."),
    "new_sentence": ("한 문장을 끝내고 잠깐 멈춘 뒤 다음 문장을 새로 시작해 보세요.", "Finish one sentence, pause briefly, and start the next as a new thought."),
    "two_versions": ("같은 문장을 평소처럼 한 번, 핵심 단어에 강조를 주어 한 번 말해 보세요.", "Say the same sentence once naturally and once emphasizing its key word."),
    "chosen_version": ("녹음을 다시 듣고 전달하려던 뜻이 더 잘 드러나는 방식 하나를 선택하세요.", "Listen again and choose the version that better expresses your intended meaning."),
    "meaningful_phrases": ("고른 문장을 짧은 의미 단위로 표시하고 단위 사이에서만 멈춰 보세요.", "Mark short meaningful phrases in your sentence and pause only between them."),
    "audible_words": ("다시 듣게 된 문장 하나만 골라 짧게 나누어 말하고, 녹음을 들으며 단어가 모두 들리는지 확인하세요.", "Choose one sentence you needed to replay, say it in short phrases, and listen for all its words."),
    "two_expressions": ("전달할 느낌 하나를 먼저 정하고 같은 문장을 두 표정으로 말해 보세요.", "Choose one feeling first and say the same sentence with two expressions."),
    "message_match": ("두 표정의 영상을 소리와 함께 다시 보고 전달할 느낌에 맞는 쪽을 하나 고르세요.", "Watch both expressions with sound and choose the one that fits your intended feeling."),
    "key_gaze": ("핵심 문장 메모를 카메라 옆에 두고 그 문장을 말할 때만 카메라 부근을 바라보세요.", "Place a key-sentence reminder beside the camera and look near it when saying that sentence."),
    "comfortable_gaze": ("핵심 문장을 마친 뒤에는 시선을 억지로 고정하지 말고 편하게 이어 말해 보세요.", "After the key sentence, continue comfortably without forcing a fixed gaze."),
    "brief_break": ("렌즈나 청중 위치를 정하고 그곳을 보며 같은 문장을 다시 말해 보세요.", "Choose the lens or an audience position and repeat the same sentence while looking there."),
    "comfortable_repeat": ("조명과 카메라 위치를 유지하고 원본과 비교해 의도하지 않은 조임이 반복되는지 확인하세요.", "Keep lighting and camera position unchanged and compare with the original for repeated unintended tightening."),
}


def next_instruction(practice, ko):
    review = practice.get("deliveryReview") or {}
    if review and (review["sameContent"] != "same" or review["sameEnvironment"] != "same"):
        return ("다음에는 같은 문장과 카메라·마이크 환경을 유지해 다시 촬영하세요. 비교 조건을 먼저 맞춘 뒤 같은 항목을 확인해요." if ko else "Use the same sentence, camera and microphone setup for the next take. Match these conditions before checking the same actions.")
    answers = review.get("answers", {})
    unresolved = [check for check in checks_for(practice, ko) if answers.get(check["id"]) != "yes"]
    if not unresolved:
        return ("확인한 두 행동을 다음 발표에서도 유지하세요. 원하면 다음 목표로 이동할 수 있어요." if ko else "Keep both confirmed actions next time. You can move on to another goal.")
    first = unresolved[0]
    if answers.get(first["id"]) == "unavailable":
        return ("원본과 재촬영을 소리와 함께 다시 재생하고, 확인하지 못한 항목 하나만 살펴보세요. 여전히 판단하기 어렵다면 같은 내용으로 다시 촬영해요." if ko else "Play the original and retry with sound and focus on the unconfirmed action. If it is still unclear, record the same content again.")
    return RETRIES[first["id"]][0 if ko else 1] + (" 같은 내용으로 30초만 다시 녹화해 확인해요." if ko else "Record the same content for thirty seconds and check again.")
