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

/** Presenter-facing interpretation; raw measurements remain available separately. */
export function findingGuidance(finding: Finding, ko: boolean) {
  const first = finding.observations?.[0];
  const reference = finding.referenceValue;
  const direction = first && typeof reference === "number" ? Math.sign(first.value - reference) : 0;
  const choices: Record<string, [string, string, string, string, string, string]> = {
    pitch_change: [direction > 0 ? "목소리가 더 높아졌어요" : direction < 0 ? "목소리가 더 낮아졌어요" : "목소리 높이에 변화가 있었어요", direction > 0 ? "your voice moved higher" : direction < 0 ? "your voice moved lower" : "your voice pitch changed", "강조가 의도대로 전달됐는지 확인하기", "Check whether the emphasis was intentional", "핵심 문장 하나에만 강조 주기", "Emphasize one key sentence"],
    pitch_variability: ["목소리의 오르내림이 다른 구간과 달랐어요", "your intonation differed from other intervals", "강조할 문장이 잘 구분되는지 듣기", "Listen for a clear emphasis", "같은 문장을 두 가지 강조로 말하기", "Try two ways of emphasizing a sentence"],
    brow_tension: ["눈썹 움직임에 구간 차이가 있었어요", "brow movement differed across intervals", "표정이 말의 의도와 맞는지 보기", "Check expression against your intention", "핵심 메시지에 맞는 표정으로 다시 말하기", "Match expression to your key message"],
    lip_tension: ["입 움직임에 구간 차이가 있었어요", "mouth movement differed across intervals", "실제 발화가 잘 들리는지 확인하기", "Check the recorded speech for clarity", "전달할 문장을 나눠 다시 말하기", "Break a sentence into clear phrases"],
    gaze: ["카메라 기준 시선 움직임에 차이가 있었어요", "the camera's gaze estimate changed", "시선이 전달 의도와 맞는지 보기", "Review whether gaze matches your intention", "핵심 문장을 말할 때 카메라 바라보기", "Look toward the camera for the key sentence"],
  };
  const row = choices[finding.id] ?? ["발표 중 관측값에 변화가 있었어요", "an observed measurement changed", "선택 구간의 전달을 확인하기", "Review delivery in the selected interval", "한 가지 전달 목표로 다시 발표하기", "Repeat with one delivery goal"];
  let observation = row[ko ? 0 : 1];
  if (first) observation = ko ? `${time(first.startMs)}–${time(first.endMs)}, ${finding.id === "pitch_change" && direction ? "앞부분과 비교해 " : ""}${observation}` : `In ${time(first.startMs)}–${time(first.endMs)}, ${observation}${finding.id === "pitch_change" && direction ? " compared with earlier intervals" : ""}.`;
  if (ko) observation += ".";
  if (!first) observation = ko ? "이 항목의 상세 관측 자료가 없습니다." : "No detailed observations are saved for this finding.";
  const count = finding.independentObservations ?? finding.assessment?.independentObservations ?? 0;
  if (count > 1) observation += ko ? ` 비슷한 변화가 겹치지 않는 ${count}개 구간에서 관찰됐습니다.` : ` A similar change appeared in ${count} non-overlapping observations.`;
  return { title: row[ko ? 2 : 3], goal: row[ko ? 4 : 5], observation,
    question: ko ? "이 변화가 의도한 강조나 표현이었나요? 영상을 먼저 확인해 주세요." : "Was this an intentional emphasis or expression? Watch the interval first." };
}
export function presentationSummary(report: AgentReport, ko: boolean) {
  if (report.priorities.length) {
    const view = findingGuidance(report.priorities[0], ko);
    return `${view.observation} ${view.question}`;
  }
  return Number(report.analysis?.coverage ?? 0) < .5
    ? ko ? "분석된 시간이 부족해 이번 발표의 개선점을 고르기 어렵습니다. 카메라와 마이크를 확인하고 조금 더 길게 발표해 주세요." : "Too little of this presentation was analyzed to select a practice focus. Check the camera and microphone and present for a little longer."
    : ko ? "이번 세션에서는 반복적으로 확인된 주요 문제를 찾지 못했습니다. 지금의 발표 흐름을 유지하며 영상을 통해 잘 전달된 부분을 확인해 보세요." : "No repeatedly observed major issue was found in this session. Keep your current approach and review the recording for what came across well.";
}
export function signalScore(value: unknown) {
  const number = typeof value === "number" ? value : typeof value === "string" && value.trim() !== "" ? Number(value) : NaN;
  return Number.isFinite(number) ? `${Math.round(number * 100)} / 100` : "—";
}
