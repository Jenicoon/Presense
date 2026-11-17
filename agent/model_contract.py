"""Pure version and measurement contracts; importing reports never loads torch."""

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from ai.concept_registry import PROPOSED_CONCEPTS_V2

VARIANT = "concept-v2"

METRIC_VERSION = "session-analysis-v5-exact7"

CONCEPT_VERSION = "literature-exact7-v2"

RAW_METRICS = (
    (
        "audio",
        "egemap_f0_semitone",
        "v2_mean_f0",
        "평균 목소리 높이 / Mean voice pitch",
    ),
    (
        "audio",
        "egemap_jitter",
        "v2_jitter",
        "목소리 주파수의 미세 변화 / Fine voice-frequency variation",
    ),
    (
        "audio",
        "egemap_shimmer_db",
        "v2_shimmer",
        "목소리 크기의 미세 변화 / Fine voice-amplitude variation",
    ),
    (
        "audio",
        "egemap_hnr_db",
        "v2_hnr",
        "음성의 조화음·잡음 비 / Voice harmonics-to-noise ratio",
    ),
    ("video", "brow_down", "v2_brow_down", "눈썹 내림 움직임 / Brow lowering movement"),
    (
        "video",
        "eye_squint",
        "v2_eye_squint",
        "눈꺼풀 조임 움직임 / Eyelid tightening movement",
    ),
    ("video", "jaw_open", "v2_jaw_open", "턱 열림 움직임 / Jaw opening movement"),
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_bundle(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if (
        manifest.get("variant") != VARIANT
        or manifest.get("conceptDefinitionVersion") != CONCEPT_VERSION
    ):
        raise ValueError("Unknown concept bundle definition")
    if manifest["conceptNames"] != [
        item.model_name_ko for item in PROPOSED_CONCEPTS_V2
    ]:
        raise ValueError("V2 concept order mismatch")
    if manifest["formula"] != {
        "baseWeight": 1.0,
        "conceptWeight": 0.03,
        "temperature": 1.0,
    }:
        raise ValueError("V2 residual formula mismatch")
    required = {
        "student.pt",
        "head.pt",
        "audio_projection_weight.npy",
        "audio_projection_bias.npy",
        "audio_projection_manifest.json",
        "geo_mean.npy",
        "geo_std.npy",
        "ege_mean.npy",
        "ege_std.npy",
    }
    if set(manifest["files"]) != required:
        raise ValueError("Incomplete V2 bundle")
    for name, digest in manifest["files"].items():
        if sha256(directory / name) != digest:
            raise ValueError("V2 bundle checksum mismatch: " + name)
    for key in ("p2", "p98"):
        v = np.asarray(manifest["scaling"][key])
        if v.shape != (7,) or not np.isfinite(v).all():
            raise ValueError("Invalid V2 training-reference scaling")
    projection = json.loads((directory / "audio_projection_manifest.json").read_text())
    if (
        projection["student_sha256"] != manifest["files"]["student.pt"]
        or projection["heldout_r2"] < 0.995
    ):
        raise ValueError("V2 audio projection was not verified for this Student")
    return manifest


def bundle_version(manifest):
    digest = hashlib.sha256(
        json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    return "exact7-v2-" + digest[:20]


def model_variant():
    value = os.getenv("PRESENSE_MODEL_VARIANT", VARIANT)
    if value not in {"legacy", VARIANT}:
        raise ValueError("Unknown model variant")
    return value


def bundle_directory():
    return Path(
        os.getenv(
            "PRESENSE_CONCEPT_V2_DIR",
            str(Path(__file__).resolve().parents[1] / "weights/concept_v2"),
        )
    )


def configured_model_version():
    if model_variant() == VARIANT:
        return bundle_version(load_bundle(bundle_directory()))
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1] / "weights"
    try:
        for name in ("student_kd_best.pt", "cbm_bi_residual_v2_w0.8_lc4.0_best.pt"):
            with (root / name).open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    except OSError:
        return "unknown"
    return "student-cbm-" + digest.hexdigest()[:16]
