export function formatCoachMeasurementNumbers(text: string) {
  return text
    .replace(/\b0\.\d{4,}\b/g, (value) => Number(value).toFixed(2))
    .replace(
      /같은 기준의 스트레스 신호: 이전 (\d+) \/ 100, 현재 (\d+) \/ 100\./,
      "이전 발표와 비교\n• 스트레스 신호: 이전 $1 / 100 → 현재 $2 / 100",
    )
    .replace(
      / 이 차이는 좋고 나쁨의 결론보다 음성·영상 측정값을 함께 살펴볼 위치를 정하는 데 사용합니다\./,
      "\n  ↳ 이 차이는 좋고 나쁨의 결론이 아니라, 함께 살펴볼 음성·영상 측정값을 찾는 데 사용합니다.",
    )
    .replace(
      / 보고서에서 선택된 검토 항목: 이전 선택된 검토 항목 없음; 현재 선택된 검토 항목 없음\./,
      "\n• 보고서 검토 항목: 이전 없음 → 현재 없음",
    )
    .replace(
      / (눈꺼풀 조임 움직임|눈썹 내림 움직임|턱 벌림 정도): 이전 ([0-9.e+-]+), 현재 ([0-9.e+-]+)\./,
      "\n• $1: 이전 $2 → 현재 $3",
    )
    .replace(
      /Stress signals under the same criteria: before (\d+) \/ 100, current (\d+) \/ 100\./,
      "Previous presentation comparison\n• Stress signal: before $1 / 100 → current $2 / 100",
    )
    .replace(
      / Use this difference to prioritize the voice and video measurements to review, rather than as a better-or-worse verdict\./,
      "\n  ↳ Use this difference to locate the voice and video measurements to review, not as a better-or-worse verdict.",
    )
    .replace(
      / Report-selected review items: previous no selected review item; current no selected review item\./,
      "\n• Report review items: before none → current none",
    )
    .replace(
      / (Eyelid tightening movement|Brow lowering movement|Jaw opening movement): before ([0-9.e+-]+), current ([0-9.e+-]+)\./,
      "\n• $1: before $2 → current $3",
    );
}
