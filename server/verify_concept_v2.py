"""Reproduce the frozen participant validation through the actual V2 runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from agent.concept_v2 import ConceptModelV2
from agent.model_contract import bundle_version, load_bundle, sha256


def verify(source: Path, bundle: Path):
    manifest = load_bundle(bundle)
    student = torch.load(bundle / "student.pt", map_location="cpu", weights_only=False)
    head = torch.load(bundle / "head.pt", map_location="cpu", weights_only=False)
    model = ConceptModelV2(student["model_state_dict"], head["state_dict"]).eval()
    cache = source / "checkpoints/binary"
    results = source / "results/redefined_7_concepts"
    frozen = np.load(results / "validation_predictions.npz")
    indices = frozen["validation_indices"]
    extraction = json.loads((cache / "pca_retrain/manifest.json").read_text())
    if not np.array_equal(indices, extraction["validation_indices"]):
        raise ValueError("Validation sample order mismatch")
    tasks = [
        "Breathing",
        "Counting1",
        "Counting2",
        "Counting3",
        "Math",
        "Reading",
        "Relax",
        "Speaking",
        "Stroop",
        "Video1",
        "Video2",
    ]
    ti = np.asarray(
        [tasks.index(extraction["sample_tasks"][i].split("_", 1)[1]) for i in indices],
        dtype=np.int64,
    )
    ff = np.load(cache / "cbm_resnet_feats.npy")[indices].astype(np.float32)
    ae = np.load(cache / "cbm_w2v_feats.npy")[indices].astype(np.float32)
    raw_geo = np.load(cache / "cbm_geometry_feats.npy")[indices].astype(np.float32)
    geo = (raw_geo - np.load(bundle / "geo_mean.npy")) / np.load(bundle / "geo_std.npy")
    ege = np.load(cache / "ege_maps_feats.npy")[indices].astype(np.float32)
    ege = (ege - np.load(bundle / "ege_mean.npy")) / (
        np.load(bundle / "ege_std.npy") + 1e-6
    )
    expected_base = np.load(
        source / "results/legacy_8182_recovery/dual_lupi_v2_logits_recovered.npy"
    )[indices]
    expected_fused = np.load(
        source
        / "results/legacy_8182_recovery/dual_lupi_v2_fused_expanded_recovered.npy"
    )[indices]
    torch.set_num_threads(4)
    logits_all, concepts_all, base_all, fused_all = [], [], [], []
    with torch.inference_mode():
        for start in range(0, len(indices), 32):
            args = [
                torch.from_numpy(x[start : start + 32]) for x in (ff, ae, geo, ti, ege)
            ]
            base, _, _, _, _, fused = model.backbone(
                *args[:4], ege_feats=args[4], return_fused=True
            )
            final, concepts, _ = model(*args)
            base_all.append(base.numpy())
            fused_all.append(fused.numpy())
            logits_all.append(final.numpy())
            concepts_all.append(concepts.numpy())
    base, fused, final, predicted = [
        np.concatenate(x) for x in (base_all, fused_all, logits_all, concepts_all)
    ]
    np.testing.assert_allclose(base, expected_base, atol=5e-5, rtol=1e-4)
    np.testing.assert_allclose(fused, expected_fused, atol=5e-5, rtol=1e-4)
    np.testing.assert_allclose(predicted, frozen["concept_pred"], atol=5e-5, rtol=1e-4)
    probability = torch.from_numpy(final).softmax(1).numpy()
    np.testing.assert_allclose(
        probability, frozen["probabilities"], atol=5e-5, rtol=1e-4
    )
    np.testing.assert_array_equal(final.argmax(1), frozen["predictions"])
    labels = frozen["labels"]
    correct = int((final.argmax(1) == labels).sum())
    expected = json.loads((results / "metrics.json").read_text())["metrics"]
    r2 = []
    for i in range(7):
        mask = frozen["concept_mask"][:, i].astype(bool)
        truth = frozen["concept_true"][mask, i].astype(float)
        estimate = predicted[mask, i].astype(float)
        r2.append(
            float(
                1
                - ((truth - estimate) ** 2).sum() / ((truth - truth.mean()) ** 2).sum()
            )
        )
    np.testing.assert_allclose(r2, expected["concept_r2"], atol=1e-5, rtol=0)
    assert correct == expected["correct"] == 97 and len(labels) == 121
    return {
        "modelVersion": bundle_version(manifest),
        "correct": correct,
        "total": len(labels),
        "accuracy": correct / len(labels),
        "conceptR2": r2,
        "meanConceptR2": float(np.mean(r2)),
        "maxBaseLogitError": float(abs(base - expected_base).max()),
        "maxConceptError": float(abs(predicted - frozen["concept_pred"]).max()),
        "projectionHeldoutR2": json.loads(
            (bundle / "audio_projection_manifest.json").read_text()
        )["heldout_r2"],
        "validationFixtureSha256": sha256(results / "validation_predictions.npz"),
        "strictStudentLoaded": True,
        "strictHeadLoaded": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, default=Path("weights/concept_v2"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.source_root, args.bundle)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered)
    print(rendered)
