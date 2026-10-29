"""Canonical metadata for the frozen seven-concept PreSense checkpoint.

The order and ``model_name_ko`` values are part of the historical model
contract.  Public labels describe what was actually calculated.  Editing this
metadata must never alter tensors, logits, or the checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptDefinition:
    index: int
    model_name_ko: str
    public_label_ko: str
    domain: str
    raw_feature: str
    construct: str
    evidence_grade: str
    evidence_role: str
    interpretation_limit: str
    reference_doi: str | None
    research_topic: str
    research_query: str
    measurement_note: str


CONCEPTS: tuple[ConceptDefinition, ...] = (
    ConceptDefinition(
        0,
        "목소리 거칠기",
        "고주파 스펙트럼 대비",
        "audio",
        "contrast_mean_5",
        "voice quality / spectral profile",
        "B-",
        "literature-supported domain; data-selected proxy",
        "Spectral contrast band 5 is not a validated perceptual roughness measure.",
        "10.1016/j.jvoice.2016.10.021",
        "concept_spectral_contrast",
        "speech stress spectral contrast spectral profile voice quality",
        "Band-5 spectral-contrast mean. It is a model proxy, not a perceptual roughness rating or a diagnosis.",
    ),
    ConceptDefinition(
        1,
        "음색 불안정성",
        "Tonnetz 축 변동성",
        "audio",
        "tonnetz_std_0",
        "complementary tonal representation",
        "C",
        "data-selected complementary proxy",
        "Tonnetz was designed for harmonic change in music and is not an established stress biomarker.",
        "10.1145/1178723.1178727",
        "concept_tonnetz_variability",
        "speech anxiety chroma dynamics tonal centroid tonnetz variability",
        "Temporal variability of Tonnetz axis 0. Tonnetz represents tonal relations; this coefficient is not an established stress marker.",
    ),
    ConceptDefinition(
        2,
        "음성 두께",
        "저차 MFCC 스펙트럼 외피",
        "audio",
        "mfcc_mean_1",
        "spectral envelope",
        "B",
        "literature-supported feature family; coefficient-specific proxy",
        "A low-order MFCC is not a direct measurement of vocal-fold or voice thickness.",
        "10.2196/36828",
        "concept_mfcc_spectral_envelope",
        "speech anxiety MFCC cepstral spectral envelope acoustic feature",
        "Mean MFCC coefficient 1. It summarizes part of the spectral envelope and does not directly measure voice thickness.",
    ),
    ConceptDefinition(
        3,
        "음성 피치",
        "평균 음성 피치 (F0)",
        "audio",
        "f0_mean",
        "voice pitch / prosody",
        "A",
        "direct literature-aligned measure",
        "F0 effects vary by speaker, sex, task, and speech type; use speaker-relative interpretation.",
        "10.1038/s41598-022-26375-9",
        "concept_mean_f0",
        "psychosocial stress speech mean fundamental frequency F0",
        "Mean acoustic fundamental frequency (F0). Interpret within speaker and context; it is not a stand-alone stress diagnosis.",
    ),
    ConceptDefinition(
        4,
        "표정 변화량",
        "얼굴 움직임 변동성",
        "video",
        "expr_variability",
        "facial motor activity",
        "B",
        "literature-supported domain; aggregate-motion proxy",
        "Mean temporal variability across blendshapes is not a specific FACS action unit.",
        "10.1016/j.cmpb.2024.108507",
        "concept_facial_variability",
        "acute stress facial action unit variability facial movement",
        "Aggregate temporal variability across facial blendshapes. It is not a manually coded FACS action unit.",
    ),
    ConceptDefinition(
        5,
        "입술 긴장도",
        "입 벌어짐 비율",
        "video",
        "lip_compression",
        "mouth-region activity",
        "B",
        "AU23-supported region; geometry proxy",
        "The current target is mouth aperture, not FACS AU23 lip tightening; speaking amount is a confounder.",
        "10.1016/j.cpnec.2023.100187",
        "concept_mouth_aperture",
        "psychosocial stress speaking mouth action lip aperture AU23",
        "Inner-lip gap divided by mouth width. Larger values mean greater aperture, not greater lip tightening; speech amount can confound it.",
    ),
    ConceptDefinition(
        6,
        "눈썹 찡그림",
        "내측 눈썹 거리",
        "video",
        "brow_tension",
        "brow / corrugator activity",
        "B",
        "AU4/corrugator-supported region; geometry proxy",
        "The current target is a distance ratio, and stress-related direction varies across people and contexts.",
        "10.1016/j.ynstr.2019.100166",
        "concept_inner_brow_distance",
        "psychosocial stress corrugator brow AU4 facial movement",
        "Inner-brow distance divided by face width. It is a geometry proxy, not observed AU4 or a direct frown score.",
    ),
)

# Candidate for a future retrained CBM.  This is intentionally separate from
# ``CONCEPTS`` so the recovered 81.82% checkpoint keeps its seven-output contract.
PROPOSED_CONCEPTS_V2: tuple[ConceptDefinition, ...] = (
    ConceptDefinition(
        0,
        "평균 음성 높이",
        "평균 음성 높이 (F0)",
        "audio",
        "F0semitoneFrom27.5Hz_sma3nz_amean",
        "mean fundamental frequency",
        "A",
        "exact acoustic measure",
        "Direction varies by speaker and speaking context; compare within speaker.",
        "10.1038/s41598-024-55550-3",
        "v2_mean_f0",
        "psychosocial stress mean fundamental frequency F0 speech",
        "eGeMAPS mean F0 in semitones; not a stand-alone stress diagnosis.",
    ),
    ConceptDefinition(
        1,
        "주파수 미세 불규칙성",
        "주파수 미세 불규칙성 (Jitter)",
        "audio",
        "jitterLocal_sma3nz_amean",
        "local jitter",
        "A-",
        "exact acoustic measure; heterogeneous association",
        "The exact measure changed in MIST but not Cyberball; direction is task-dependent.",
        "10.1038/s41598-024-55550-3",
        "v2_jitter",
        "psychosocial stress local jitter vocal frequency variation",
        "eGeMAPS local jitter; a voice-production measure, not a universal stress direction.",
    ),
    ConceptDefinition(
        2,
        "진폭 미세 불규칙성",
        "진폭 미세 불규칙성 (Shimmer)",
        "audio",
        "shimmerLocaldB_sma3nz_amean",
        "local shimmer",
        "A",
        "exact acoustic measure",
        "Effects depend on task and speech type; do not prescribe increasing or decreasing it.",
        "10.1038/s41598-024-55550-3",
        "v2_shimmer",
        "psychosocial stress local shimmer vocal amplitude variation",
        "eGeMAPS local shimmer in dB; interpret only relative to the same speaker.",
    ),
    ConceptDefinition(
        3,
        "조화음-잡음비",
        "조화음-잡음비 (HNR)",
        "audio",
        "HNRdBACF_sma3nz_amean",
        "harmonics-to-noise ratio",
        "A",
        "exact acoustic measure",
        "Prior psychological-stress findings are mixed even though the controlled study found a change.",
        "10.1038/s41598-024-55550-3",
        "v2_hnr",
        "psychosocial stress harmonics to noise ratio HNR voice",
        "eGeMAPS HNR; not equivalent to perceived roughness and not a diagnosis.",
    ),
    ConceptDefinition(
        4,
        "눈썹 내림 움직임",
        "눈썹 내림 움직임",
        "video",
        "mean(browDownLeft,browDownRight)",
        "bilateral brow-down movement; AU4 bridge",
        "A-",
        "direct MediaPipe measure; expert-validated blendshape-to-AU bridge",
        "This is a MediaPipe movement coefficient, not certified FACS coding or a direct stress score.",
        "10.1016/j.chbr.2026.101125",
        "v2_brow_down",
        "acute stress brow lowerer AU4 MediaPipe blendshape",
        "Mean bilateral browDown score over valid frames; describe only the observed movement.",
    ),
    ConceptDefinition(
        5,
        "눈꺼풀 조임 움직임",
        "눈꺼풀 조임 움직임",
        "video",
        "mean(eyeSquintLeft,eyeSquintRight)",
        "bilateral eyelid tightening; AU7 bridge",
        "A",
        "direct MediaPipe measure; AU7 has the strongest prospective stress signal in a TSST pilot",
        "The AU7 association differed across stress markers and is not diagnostic for an individual.",
        "10.1016/j.cpnec.2023.100187",
        "v2_eye_squint",
        "psychosocial stress eyelid tightener AU7 MediaPipe eyeSquint",
        "Mean bilateral eyeSquint score over valid frames; lighting, glasses, and gaze can affect it.",
    ),
    ConceptDefinition(
        6,
        "턱 열림 움직임",
        "턱 열림 움직임",
        "video",
        "mean(jawOpen)",
        "jaw opening; AU26 bridge",
        "B+",
        "direct MediaPipe measure; corresponding AU26 examined in TSST research",
        "Jaw opening is strongly affected by speech content and articulation, so it is not stress-specific.",
        "10.1016/j.cpnec.2023.100187",
        "v2_jaw_open",
        "psychosocial stress jaw drop AU26 MediaPipe jawOpen speaking",
        "Mean jawOpen score over valid frames; use as presentation behavior feedback, not diagnosis.",
    ),
)

MODEL_CONCEPT_NAMES: tuple[str, ...] = tuple(item.model_name_ko for item in CONCEPTS)
PUBLIC_CONCEPT_LABELS: tuple[str, ...] = tuple(
    item.public_label_ko for item in CONCEPTS
)
PUBLIC_LABEL_BY_MODEL_NAME: dict[str, str] = {
    item.model_name_ko: item.public_label_ko for item in CONCEPTS
}
CONCEPT_BY_MODEL_NAME: dict[str, ConceptDefinition] = {
    item.model_name_ko: item for item in CONCEPTS
}


def public_concept_values(values: dict[str, float]) -> dict[str, float]:
    """Relabel model outputs without changing their values or order."""
    return {
        PUBLIC_LABEL_BY_MODEL_NAME.get(name, name): value
        for name, value in values.items()
    }
