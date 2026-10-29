"""Package a candidate in a new directory; never overwrite legacy model artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from agent.model_contract import CONCEPT_VERSION, METRIC_VERSION, VARIANT, sha256
from ai.concept_registry import PROPOSED_CONCEPTS_V2


def package(source: Path, output: Path):
    if output.exists():
        raise FileExistsError(
            "Use a new bundle directory; existing artifacts are never overwritten"
        )
    results = source / "results/redefined_7_concepts"
    recovery = source / "results/legacy_8182_recovery"
    cache = source / "checkpoints/binary"
    extraction = json.loads((cache / "pca_retrain/manifest.json").read_text())
    train = np.array(extraction["train_indices"], dtype=int)
    validation = np.array(extraction["validation_indices"], dtype=int)
    tasks = extraction["sample_tasks"]
    frozen = np.load(results / "validation_predictions.npz")
    if not np.array_equal(validation, frozen["validation_indices"]):
        raise ValueError("Projection and frozen model validation splits differ")
    if len(set(train) & set(validation)) or len(set(train) | set(validation)) != len(
        tasks
    ):
        raise ValueError("Invalid held-out projection split")
    if {tasks[i].split("_")[0] for i in train} & {
        tasks[i].split("_")[0] for i in validation
    }:
        raise ValueError("Projection participants overlap")
    raw = np.load(cache / "pca_retrain/audio_raw_768.npy").astype(np.float64)
    target = np.load(cache / "cbm_w2v_feats.npy").astype(np.float64)
    if (
        raw.shape != (len(tasks), 768)
        or target.shape != (len(tasks), 256)
        or not (np.isfinite(raw).all() and np.isfinite(target).all())
    ):
        raise ValueError("Projection cache contract mismatch")
    x_mean, y_mean = raw[train].mean(0), target[train].mean(0)
    x, y = raw[train] - x_mean, target[train] - y_mean
    weight = x.T @ np.linalg.solve(x @ x.T + 1e-4 * np.eye(len(train)), y)
    bias = y_mean - x_mean @ weight
    # Validate the exported float32 coefficients, not only the fit in float64.
    weight, bias = weight.astype(np.float32), bias.astype(np.float32)
    predicted = raw[validation].astype(np.float32) @ weight + bias
    expected = target[validation]
    mae = float(np.abs(predicted - expected).mean())
    r2 = float(
        1
        - np.square(predicted - expected).sum()
        / np.square(expected - expected.mean(0)).sum()
    )
    if mae >= 0.01 or r2 <= 0.995:
        raise ValueError("Held-out audio projection failed; refuse packaging")
    output.mkdir(parents=True)
    shutil.copy2(
        recovery / "dual_lupi_v2_student_best_recovered.pt", output / "student.pt"
    )
    shutil.copy2(results / "cbm_head_candidate.pt", output / "head.pt")
    np.save(output / "audio_projection_weight.npy", weight.T)
    np.save(output / "audio_projection_bias.npy", bias)
    projection = {
        "source_model": "facebook/wav2vec2-base",
        "student_sha256": sha256(output / "student.pt"),
        "target_features": "cbm_w2v_feats.npy",
        "method": "train-participant affine ridge; exported float32 validation",
        "heldout_mae": mae,
        "heldout_r2": r2,
        "train_count": len(train),
        "validation_count": len(validation),
        "raw_cache_sha256": sha256(cache / "pca_retrain/audio_raw_768.npy"),
        "target_cache_sha256": sha256(cache / "cbm_w2v_feats.npy"),
        "sample_order_sha256": hashlib.sha256("\n".join(tasks).encode()).hexdigest(),
    }
    (output / "audio_projection_manifest.json").write_text(
        json.dumps(projection, indent=2)
    )
    geometry = np.load(cache / "cbm_geometry_feats.npy").astype(np.float64)
    normalized = np.load(cache / "dual_geo_scaled.npy").astype(np.float64)
    # Recover the exact historical affine normalization on training participants.
    # The published legacy scaler replaced two tiny denominators by 1.0, which
    # does not reproduce this recovered Student's geometry cache.
    means, scales = [], []
    for feature in range(24):
        x = geometry[train, :, feature].reshape(-1)
        y = normalized[train, :, feature].reshape(-1)
        slope, offset = np.linalg.lstsq(
            np.column_stack([x, np.ones(len(x))]), y, rcond=None
        )[0]
        if not np.isfinite(slope) or slope <= 0:
            raise ValueError("Invalid historical geometry transform")
        means.append(-offset / slope)
        scales.append(1 / slope)
    means, scales = (
        np.asarray(means, dtype=np.float32),
        np.asarray(scales, dtype=np.float32),
    )
    reconstructed = (geometry.astype(np.float32) - means) / scales
    geometry_error = float(
        abs(reconstructed[validation] - normalized[validation]).max()
    )
    if geometry_error > 1e-4:
        raise ValueError("Held-out geometry preprocessing cannot be reproduced")
    np.save(output / "geo_mean.npy", means)
    np.save(output / "geo_std.npy", scales)
    ege = np.load(cache / "ege_maps_feats.npy").astype(np.float32)
    np.save(output / "ege_mean.npy", ege.mean(0))
    np.save(output / "ege_std.npy", ege.std(0))
    metrics = json.loads((results / "metrics.json").read_text())
    manifest = {
        "variant": VARIANT,
        "metricDefinitionVersion": METRIC_VERSION,
        "conceptDefinitionVersion": CONCEPT_VERSION,
        "conceptNames": [i.model_name_ko for i in PROPOSED_CONCEPTS_V2],
        "scaling": metrics["scaling"],
        "formula": {"baseWeight": 1.0, "conceptWeight": 0.03, "temperature": 1.0},
        "featureContract": {
            "frames": [16, 512],
            "audio": [256],
            "geometry": [16, 24],
            "eGeMAPS": [88],
            "audioSampleRate": 16000,
            "audioWindowSamples": 160000,
            "egeRawIndices": [0, 30, 32, 34],
            "videoRawIndices": [[14, 15], [19, 20], [21]],
            "inputScalerScope": "historical normalization preserved; geometry affine recovered on training participants and verified held-out; eGeMAPS uses historical full-cohort statistics",
            "geometryTransformMaxHeldoutError": geometry_error,
            "geometryEpsilon": 0.0,
            "conceptScalerScope": "training participants p2-p98; not medical probabilities",
        },
        "validation": metrics["metrics"],
        "limitations": [
            "Previously inspected external participant split; not an independent final test",
            "Eye-squint internal fold R2 reached 0.357",
            "Concept mean replacement did not change validation correct count",
            "No causal or diagnostic interpretation",
        ],
        "files": {p.name: sha256(p) for p in sorted(output.iterdir())},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "projectionHeldoutR2": r2,
                "projectionHeldoutMAE": mae,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    package(args.source_root, args.output_dir)
