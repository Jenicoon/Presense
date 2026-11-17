"""Frozen recovered KD Student architecture, isolated from training scripts.

Parameter names and evaluation operations reproduce legacy_8182_recovery.
No key renaming, partial loading or training side effects are permitted.
"""

from __future__ import annotations

import torch
from torch import nn

VIDEO_EMB_DIM = 512
AUDIO_EMB_DIM = 256
EGEMAP_DIM = 88
NUM_TASKS = 11
TASK_EMB_DIM = 8
GEO_INPUT_DIM = 24
GEO_HIDDEN_DIM = 64
FUSED_EXP_DIM = 320


class CrossModalAttention(nn.Module):
    """
    Q: audio_emb (B, a_dim) — 무엇을 찾을지
    K, V: lstm_out (B, T, v_dim) — 영상 프레임 시퀀스
    → 음성이 관련 프레임에 주목 → audio-guided video representation
    """

    def __init__(
        self,
        v_dim: int = 256,
        a_dim: int = 256,
        d_k: int = 64,
        out_dim: int = 256,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.q_proj = nn.Linear(a_dim, d_k)
        self.k_proj = nn.Linear(v_dim, d_k)
        self.v_proj = nn.Linear(v_dim, out_dim)
        self.out_proj = nn.Linear(out_dim + a_dim, out_dim)
        self.norm = nn.LayerNorm(out_dim)
        self.drop = nn.Dropout(dropout)
        self.scale = d_k**-0.5

    def forward(self, lstm_out: torch.Tensor, a_emb: torch.Tensor):
        """
        lstm_out : (B, T, v_dim)
        a_emb    : (B, a_dim)
        → fused (B, out_dim), attn_weights (B, T)
        """
        Q = self.q_proj(a_emb).unsqueeze(1)  # (B, 1, d_k)
        K = self.k_proj(lstm_out)  # (B, T, d_k)
        V = self.v_proj(lstm_out)  # (B, T, out_dim)
        scores = Q @ K.transpose(-1, -2) * self.scale  # (B, 1, T)
        weights = torch.softmax(scores, dim=-1)  # (B, 1, T)
        attended = self.drop(weights @ V).squeeze(1)  # (B, out_dim)
        fused = self.out_proj(torch.cat([attended, a_emb], dim=1))
        return self.norm(fused), weights.squeeze(1)


class TemporalAttentionPool(nn.Module):
    """(B, T, d) → (B, d)  학습된 스칼라 어텐션 가중합."""

    def __init__(self, d: int, dropout: float = 0.1):
        super().__init__()
        self.score = nn.Linear(d, 1)
        self.drop = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = torch.softmax(self.score(x), dim=1)  # (B, T, 1)
        return (self.drop(w) * x).sum(dim=1)


class GeometryGRUAttn(nn.Module):
    """
    GeometryGRU 개선판.
    마지막 hidden state → Temporal Attention Pool:
    발표 중 스트레스 피크 구간(질의응답, 슬라이드 전환 등)을 선택적으로 포착.
    """

    def __init__(
        self,
        input_dim: int = GEO_INPUT_DIM,
        hidden_dim: int = GEO_HIDDEN_DIM,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.gru = nn.GRU(input_dim, hidden_dim, batch_first=True)
        self.pool = TemporalAttentionPool(hidden_dim, dropout=dropout * 0.5)
        self.drop = nn.Dropout(dropout)
        self.norm = nn.LayerNorm(hidden_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.gru(x)  # (B, T, 64)
        pooled = self.pool(out)  # (B, 64)
        return self.norm(self.drop(pooled))


class DualBranchStudentCMABiV2(nn.Module):
    """
    V2 Student (배포 모델) — eGeMAPS late fusion + GeometryGRUAttn.

    V1(CMABi) 대비 변경:
      1. GeometryGRUAttn  — 마지막 hidden state → temporal attention pool
      2. eGeMAPS late fusion — fused_expanded(320) 이후 eGeMAPS(88) 추가
         cross_attn a_dim=256 유지 → V1 가중치 완전 전이 가능

    fused_expanded = 320 (V1과 동일) → CBM 호환.
    ege_feats=None이면 V1 CMABi와 동일하게 동작 (하위 호환).
    """

    BI_HIDDEN = 128
    EGE_PROJ_DIM = 64

    def __init__(self, num_classes: int = 2, dropout: float = 0.3):
        super().__init__()
        self.video_lstm = nn.LSTM(
            VIDEO_EMB_DIM,
            self.BI_HIDDEN,
            batch_first=True,
            bidirectional=True,
        )
        self.geo_gru = GeometryGRUAttn(
            GEO_INPUT_DIM, GEO_HIDDEN_DIM, dropout=dropout * 0.7
        )
        self.cross_attn = CrossModalAttention(
            v_dim=self.BI_HIDDEN * 2,
            a_dim=AUDIO_EMB_DIM,  # a_dim=256, V1과 동일
            d_k=64,
            out_dim=self.BI_HIDDEN * 2,
            dropout=dropout * 0.3,
        )
        self.ege_branch = nn.Sequential(
            nn.Linear(EGEMAP_DIM, self.EGE_PROJ_DIM),
            nn.ReLU(),
            nn.LayerNorm(self.EGE_PROJ_DIM),
        )
        self.ege_fusion = nn.Sequential(
            nn.Linear(FUSED_EXP_DIM + self.EGE_PROJ_DIM, FUSED_EXP_DIM),
            nn.ReLU(),
            nn.LayerNorm(FUSED_EXP_DIM),
        )
        self.task_emb = nn.Embedding(NUM_TASKS, TASK_EMB_DIM)
        self.classifier = nn.Sequential(
            nn.Linear(FUSED_EXP_DIM + TASK_EMB_DIM, 128),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(128, num_classes),
        )

    def forward(
        self,
        frame_feats: torch.Tensor,
        audio_emb: torch.Tensor,
        geometry: torch.Tensor,
        task_id: torch.Tensor,
        ege_feats: torch.Tensor | None = None,
        return_fused: bool = False,
    ):
        """
        frame_feats : (B, T, 512)
        audio_emb   : (B, 256)
        geometry    : (B, T, 24)
        task_id     : (B,)
        ege_feats   : (B, 88)  z-score 정규화된 eGeMAPS (없으면 skip)
        """
        lstm_out, _ = self.video_lstm(frame_feats)  # (B, T, 256)
        g_emb = self.geo_gru(geometry)  # (B, 64)
        fused, attn_w = self.cross_attn(lstm_out, audio_emb)  # (B, 256), (B, T)
        fused_expanded = torch.cat([fused, g_emb], dim=1)  # (B, 320)

        if ege_feats is not None:
            e_emb = self.ege_branch(ege_feats)  # (B, 64)
            fused_expanded = self.ege_fusion(
                torch.cat([fused_expanded, e_emb], dim=1)
            )  # (B, 320)

        t_emb = self.task_emb(task_id)
        logits = self.classifier(torch.cat([fused_expanded, t_emb], dim=1))
        if return_fused:
            return logits, None, None, audio_emb, attn_w, fused_expanded
        return logits, None, None, audio_emb, attn_w
