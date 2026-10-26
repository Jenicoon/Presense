const names: Record<string, [string, string]> = {
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
  "목소리 거칠기": ["목소리 거칠기 패턴", "Voice roughness pattern"],
  "음색 불안정성": ["음색 변화 패턴", "Voice timbre variation pattern"],
  "음성 두께": ["음성 두께 패턴", "Voice depth pattern"],
  "음성 피치": ["목소리 높이 패턴", "Voice pitch pattern"],
  "표정 변화량": ["표정 변화 패턴", "Facial movement pattern"],
  "입술 긴장도": ["입술 모양 패턴", "Lip shape pattern"],
  "눈썹 찡그림": ["눈썹 움직임 패턴", "Brow movement pattern"],
  voice: ["목소리 패턴", "Voice pattern"],
};
export function measurementLabel(key: string, ko: boolean) {
  return (
    names[key]?.[ko ? 0 : 1] ?? (ko ? "추가 관측값" : "Additional measurement")
  );
}
