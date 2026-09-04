"""
Wav2Vec2 768-dim → PCA(256-dim) 프로젝션 추출 스크립트.

cbm_w2v_feats.npy(N, 256)와 동일한 샘플 순서로 Wav2Vec2 768-dim을 뽑고
PCA를 피팅해 inference용 프로젝션 가중치를 저장.

출력:
  checkpoints/binary/audio_pca_components.npy  (256, 768)
  checkpoints/binary/audio_pca_mean.npy        (768,)
"""

import sys
import numpy as np
import torch
from pathlib import Path

_root = Path(__file__).resolve().parent.parent.parent
for p in [_root, _root/'ai', _root/'ai'/'data', _root/'ai'/'train']:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import config
from dataset_e2e import build_sample_list, load_audio

DEVICE   = 'mps' if torch.backends.mps.is_available() else \
           'cuda' if torch.cuda.is_available() else 'cpu'
CKPT_DIR = config.CHECKPOINTS_DIR / 'binary'
OUT_COMP = CKPT_DIR / 'audio_pca_components.npy'
OUT_MEAN = CKPT_DIR / 'audio_pca_mean.npy'
N_COMP   = 256


def main():
    labels_df  = __import__('pandas').read_csv(config.LABELS_FILE)
    labels_map = dict(zip(labels_df.iloc[:, 0], labels_df.iloc[:, 1]))
    samples    = build_sample_list(labels_map)
    N          = len(samples)
    print(f"총 샘플: {N}")

    from transformers import Wav2Vec2Model
    wav2vec = Wav2Vec2Model.from_pretrained('facebook/wav2vec2-base').to(DEVICE)
    wav2vec.eval()
    for p in wav2vec.parameters():
        p.requires_grad = False
    print("Wav2Vec2 로드 완료")

    raw768 = np.zeros((N, 768), dtype=np.float32)
    for i, s in enumerate(samples):
        try:
            audio = load_audio(Path(s['path']))
            wav   = torch.tensor(audio).unsqueeze(0).to(DEVICE)
            with torch.no_grad():
                h = wav2vec(wav).last_hidden_state.mean(dim=1)  # (1, 768)
            raw768[i] = h.squeeze(0).cpu().numpy()
        except Exception as e:
            print(f"  [{i}] {s.get('task','?')}: {e}")
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{N} 완료")

    print("PCA 피팅 중...")
    from sklearn.decomposition import PCA
    pca = PCA(n_components=N_COMP)
    pca.fit(raw768)

    np.save(OUT_COMP, pca.components_.astype(np.float32))  # (256, 768)
    np.save(OUT_MEAN, pca.mean_.astype(np.float32))        # (768,)
    print(f"저장 완료: {OUT_COMP}")
    print(f"설명 분산: {pca.explained_variance_ratio_.sum():.3f}")

    proj = (raw768 - pca.mean_) @ pca.components_.T  # (N, 256)
    print(f"PCA 출력 shape: {proj.shape}")
    print(f"원본 cbm_w2v_feats: {np.load(CKPT_DIR / 'cbm_w2v_feats.npy').shape}")


if __name__ == '__main__':
    main()
