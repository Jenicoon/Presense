"""Versioned V2 candidate: recovered Student + independently scaled auxiliary head."""

from __future__ import annotations

from torch import nn

from ai.models.recovered_student import DualBranchStudentCMABiV2


class ResidualConceptHeadV2(nn.Module):
    def __init__(self):
        super().__init__()
        self.concept_predictor = nn.Sequential(
            nn.Linear(320, 128), nn.ReLU(), nn.Dropout(0.3), nn.Linear(128, 7)
        )
        self.concept_classifier = nn.Sequential(
            nn.Linear(7, 32), nn.ReLU(), nn.Linear(32, 2)
        )

    def forward(self, fused, base_logits):
        concepts = self.concept_predictor(fused)
        return base_logits + 0.03 * self.concept_classifier(concepts), concepts


class ConceptModelV2(nn.Module):
    def __init__(self, student_state, head_state):
        super().__init__()
        self.backbone = DualBranchStudentCMABiV2(dropout=0.0)
        self.backbone.load_state_dict(student_state, strict=True)
        self.cbm = ResidualConceptHeadV2()
        self.cbm.load_state_dict(head_state, strict=True)

    def forward(self, ff, ae, geo, ti, ege=None):
        if ege is None:
            raise ValueError("V2 requires the paired 88-feature eGeMAPS input")
        logits, _, _, _, attention, fused = self.backbone(
            ff, ae, geo, ti, ege_feats=ege, return_fused=True
        )
        final, concepts = self.cbm(fused, logits)
        return final, concepts, attention
