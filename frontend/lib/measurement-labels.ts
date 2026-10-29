const names: Record<string, [string, string]> = {
  "egemap_f0_semitone": ["평균 목소리 높이 (반음)", "Mean voice pitch (semitones)"],
  "egemap_jitter": ["주파수 미세 불규칙성 (Jitter)", "Local jitter"],
  "egemap_shimmer_db": ["진폭 미세 불규칙성 (dB)", "Local shimmer (dB)"],
  "egemap_hnr_db": ["조화음-잡음비 (dB)", "Harmonics-to-noise ratio (dB)"],
  "brow_down": ["눈썹 내림 움직임", "Brow lowering movement"],
  "eye_squint": ["눈꺼풀 조임 움직임", "Eyelid tightening movement"],
  "jaw_open": ["턱 열림 움직임", "Jaw opening movement"],
  "평균 음성 높이": ["평균 목소리 높이 예측값", "Predicted mean voice pitch"],
  "주파수 미세 불규칙성": ["Jitter 예측값", "Predicted jitter"],
  "진폭 미세 불규칙성": ["Shimmer 예측값", "Predicted shimmer"],
  "조화음-잡음비": ["HNR 예측값", "Predicted HNR"],
  "눈썹 내림 움직임": ["눈썹 내림 예측값", "Predicted brow lowering"],
  "눈꺼풀 조임 움직임": ["눈꺼풀 조임 예측값", "Predicted eyelid tightening"],
  "턱 열림 움직임": ["턱 열림 예측값", "Predicted jaw opening"],

  f0_mean: ["평균 목소리 높이 (Hz)", "Mean voice pitch (Hz)"],
  f0_std: ["목소리 높이 변동 (Hz)", "Voice pitch variation (Hz)"],
  voiced_ratio: ["유성음 비율", "Voiced audio ratio"],
  energy_variability: ["음성 에너지 변화", "Voice energy variation"],
  mean_ear: ["눈 열림 추정치", "Eye opening estimate"],
  blink_count: ["눈 감김 프레임 추정치", "Closed-eye frame estimate"],
  gaze_stability: ["시선 안정도 추정치", "Gaze stability estimate"],
  eye_contact_score: ["시선 안정도 추정치", "Gaze stability estimate"],
  head_movement: ["머리 움직임 추정치", "Head movement estimate"],
  lip_tension: ["입 벌림 비율", "Mouth aperture ratio"],
  brow_tension: ["눈썹 움직임 추정치", "Brow movement estimate"],
  "목소리 거칠기": ["고주파 스펙트럼 대비 예측값", "Predicted high-band spectral contrast"],
  "음색 불안정성": ["Tonnetz 축 변동성 예측값", "Predicted Tonnetz variability"],
  "음성 두께": ["저차 MFCC 예측값", "Predicted low-order MFCC"],
  "음성 피치": ["목소리 높이 패턴", "Voice pitch pattern"],
  "표정 변화량": ["표정 변화 패턴", "Facial movement pattern"],
  "입술 긴장도": ["입 벌어짐 비율 예측값", "Predicted mouth aperture ratio"],
  "눈썹 찡그림": ["내측 눈썹 거리 예측값", "Predicted inner-brow distance"],
  voice: ["목소리 패턴", "Voice pattern"],
};
export function measurementLabel(key: string, ko: boolean) {
  return (
    names[key]?.[ko ? 0 : 1] ?? (ko ? "추가 관측값" : "Additional measurement")
  );
}
