import type { AgentReport } from "@/lib/agent-report";
import { measurementLabel } from "@/lib/measurement-labels";

type Finding = AgentReport["priorities"][number];
export function matchesLanguage(text: string | undefined, ko: boolean) {
  if (!text?.trim()) return false;
  return /[가-힣]/.test(text) === ko;
}
export function bilingualLabel(text: string, ko: boolean, fallback: string) {
  const parts = text.split(" / ");
  const selected = parts[ko ? 0 : parts.length - 1];
  return matchesLanguage(selected, ko) ? selected : fallback;
}
function time(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
export function findingText(finding: Finding, ko: boolean) {
  const label = bilingualLabel(finding.label, ko, measurementLabel(finding.metric ?? finding.id, ko));
  const first = finding.observations?.[0];
  const reference = finding.referenceValue;
  const unit = finding.metric?.startsWith("f0_") ? " Hz" : "";
  const span = first ? `${time(first.startMs)}–${time(first.endMs)}` : "";
  const observation = matchesLanguage(finding.observationText, ko) ? finding.observationText : first
    ? (ko ? `${span} 구간의 ${label} 값은 ${first.value.toFixed(2)}${unit}였습니다.` :
      `${label} was ${first.value.toFixed(2)}${unit} in ${span}.`) +
      (typeof reference === "number" ? (ko ? ` 앞선 구간의 기준값은 ${reference.toFixed(2)}${unit}입니다.` :
        ` The reference in earlier intervals was ${reference.toFixed(2)}${unit}.`) : "")
    : (ko ? "이 항목의 상세 관측 자료가 없습니다." : "No detailed observations are saved for this finding.");
  const review = matchesLanguage(finding.reviewAction, ko) ? finding.reviewAction : ko
    ? "영상에서 이 변화가 의도한 강조와 전달에 맞는지 확인해 보세요."
    : "Review whether this change matches your intended emphasis and delivery.";
  const practice = matchesLanguage(finding.practiceSuggestion, ko) ? finding.practiceSuggestion : ko
    ? "같은 내용을 30초 다시 발표하고, 같은 측정값과 실제 전달을 함께 비교해 보세요."
    : "Repeat the same content for 30 seconds, then compare the same measurements alongside the recording.";
  return { label, observation, review, practice };
}
export function localizedSummary(report: AgentReport, ko: boolean) {
  if ((!report.language || report.language === (ko ? "ko" : "en")) && matchesLanguage(report.summaryText, ko)) return report.summaryText;
  if (report.priorities?.length) return findingText(report.priorities[0], ko).observation;
  const peak = report.observationReport?.peakSegment;
  if (!peak) return ko ? "분석할 수 있는 구간이 없습니다. 카메라와 마이크를 확인해 주세요." :
    "No usable analysis interval is available. Check the camera and microphone.";
  return ko ? `${time(peak.startMs)}–${time(peak.endMs)} 구간의 모델 점수가 ${peak.stressScore.toFixed(3)}으로 가장 높았습니다. 반복적으로 확인된 주요 문제는 찾지 못했습니다.` :
    `The model score peaked at ${peak.stressScore.toFixed(3)} in ${time(peak.startMs)}–${time(peak.endMs)}. No repeatedly observed major issue was found.`;
}
export function sceneText(value: string, ko: boolean) {
  const names: Record<string, [string, string]> = {
    "Live Camera": ["실시간 카메라", "Live Camera"], "실시간 카메라": ["실시간 카메라", "Live Camera"],
    "Classroom Audience": ["강의실 청중", "Classroom Audience"], "강의실 청중": ["강의실 청중", "Classroom Audience"],
    "Interview Panel": ["면접 패널", "Interview Panel"], "면접 패널": ["면접 패널", "Interview Panel"],
    "Presentation Slides": ["발표 슬라이드", "Presentation Slides"], "발표 슬라이드": ["발표 슬라이드", "Presentation Slides"],
    "Slides in Classroom": ["강의실 속 슬라이드", "Slides in Classroom"], "강의실 속 슬라이드": ["강의실 속 슬라이드", "Slides in Classroom"],
    Unlabeled: ["환경 미지정", "Unlabeled"],
    Camera: ["카메라", "Camera"], 카메라: ["카메라", "Camera"],
    Classroom: ["강의실", "Classroom"], 강의실: ["강의실", "Classroom"],
    Interview: ["면접", "Interview"], 면접: ["면접", "Interview"],
  };
  return names[value]?.[ko ? 0 : 1] ?? value;
}

export function durationText(value: string, ko: boolean) {
  const match = value.match(/^(\d+)m\s*(\d+)s$/);
  return ko && match ? `${Number(match[1])}분 ${Number(match[2])}초` : value;
}
