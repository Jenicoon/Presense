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
  const comparable = typeof first?.value === "number" && Number.isFinite(first.value) && typeof reference === "number" && Number.isFinite(reference);
  const direction = comparable ? Math.sign(first!.value - reference!) : null;
  const choices: Record<string, [string, string, string, string, string, string]> = {
    pitch_change: [direction !== null && direction > 0 ? "목소리가 더 높아졌어요" : direction !== null && direction < 0 ? "목소리가 더 낮아졌어요" : "목소리 높이에 변화가 있었어요", direction !== null && direction > 0 ? "your voice moved higher" : direction !== null && direction < 0 ? "your voice moved lower" : "your voice pitch changed", "강조가 의도대로 전달됐는지 확인하기", "Check whether the emphasis was intentional", "핵심 문장 하나에만 강조 주기", "Emphasize one key sentence"],
    pitch_variability: [direction === null ? "앞부분과 목소리 높낮이의 변화 폭을 비교할 자료가 부족해요" : direction > 0 ? "목소리 높낮이의 변화 폭이 앞부분보다 컸어요" : direction < 0 ? "목소리 높낮이의 변화 폭이 앞부분보다 작았어요" : "목소리 높낮이의 변화 폭은 앞부분과 비슷했어요", direction === null ? "there is not enough data to compare pitch variation with earlier in the presentation" : direction > 0 ? "your pitch varied more than earlier in the presentation" : direction < 0 ? "your pitch varied less than earlier in the presentation" : "your pitch varied about as much as earlier in the presentation", "강조할 문장이 잘 구분되는지 듣기", "Listen for a clear emphasis", "같은 문장을 두 가지 강조로 말하기", "Try two ways of emphasizing a sentence"],
    brow_tension: [direction === null ? "앞부분과 눈썹 모양을 비교할 자료가 부족해요" : direction > 0 ? "눈썹이 앞부분보다 더 내려간 모습으로 측정됐어요" : direction < 0 ? "눈썹이 앞부분보다 덜 내려간 모습으로 측정됐어요" : "눈썹이 내려간 정도는 앞부분과 비슷했어요", direction === null ? "there is not enough data to compare eyebrow lowering with earlier in the presentation" : direction > 0 ? "your eyebrows were estimated to be more lowered than earlier in the presentation" : direction < 0 ? "your eyebrows were estimated to be less lowered than earlier in the presentation" : "the estimated eyebrow lowering was similar to earlier in the presentation", "표정이 말의 의도와 맞는지 보기", "Check expression against your intention", "핵심 메시지에 맞는 표정으로 다시 말하기", "Match expression to your key message"],
    lip_tension: [direction === null ? "앞부분과 입이 벌어진 정도를 비교할 자료가 부족해요" : direction > 0 ? "입이 벌어진 정도가 앞부분보다 컸어요" : direction < 0 ? "입이 벌어진 정도가 앞부분보다 작았어요" : "입이 벌어진 정도는 앞부분과 비슷했어요", direction === null ? "there is not enough data to compare mouth opening with earlier in the presentation" : direction > 0 ? "your mouth was more open than earlier in the presentation" : direction < 0 ? "your mouth was less open than earlier in the presentation" : "your mouth opening was similar to earlier in the presentation", "말소리가 또렷하게 들리는지 듣기", "Listen for clear speech", "전달할 문장을 나눠 다시 말하기", "Break a sentence into clear phrases"],
    gaze: ["카메라 기준 시선 움직임에 차이가 있었어요", "the camera's gaze estimate changed", "시선이 전달 의도와 맞는지 보기", "Review whether gaze matches your intention", "핵심 문장을 말할 때 카메라 바라보기", "Look toward the camera for the key sentence"],
  };
  const row = choices[finding.id] ?? ["발표 중 관측값에 변화가 있었어요", "an observed measurement changed", "선택 구간의 전달을 확인하기", "Review delivery in the selected interval", "한 가지 전달 목표로 다시 발표하기", "Repeat with one delivery goal"];
  let observation = row[ko ? 0 : 1];
  if (first) observation = ko ? `${time(first.startMs)}–${time(first.endMs)}, ${finding.id === "pitch_change" && direction ? "앞부분과 비교해 " : ""}${observation}` : `In ${time(first.startMs)}–${time(first.endMs)}, ${observation}${finding.id === "pitch_change" && direction ? " compared with earlier intervals" : ""}.`;
  if (ko) observation += ".";
  if (!first) observation = ko ? "이 항목의 상세 관측 자료가 없습니다." : "No detailed observations are saved for this finding.";
  const count = finding.observations?.length ?? 0;
  if (count > 1) observation += ko ? ` 함께 확인할 영상은 ${count}곳이에요.` : ` There are ${count} recorded intervals to review together.`;
  return { title: row[ko ? 2 : 3], goal: row[ko ? 4 : 5], observation,
    question: ({
      pitch_change: ["높낮이가 바뀌는 순간에 중요한 문장이 구분되는지 들어보세요. 문장 끝의 쉼과 다음 문장 시작도 따로 들어보세요.", "Listen for whether a pitch change marks a key sentence. Separately check sentence-end pauses and the next sentence start."],
      pitch_variability: ["고른 구간을 듣고 가장 중요한 문장 하나를 직접 골라보세요. 그 문장이 나머지와 구분되는지, 의미가 끝나기 전에 끊겨 들리는지 확인하세요.", "Choose the key sentence yourself. Listen for whether it stands out and whether the thought sounds interrupted before it is complete."],
      lip_tension: ["입 모양만으로 발음이 좋거나 나쁜지는 알 수 없어요. 이 장면을 소리와 함께 재생해 보세요. 잘 들리면 지금 방식을 유지하고, 다시 듣게 된 문장이 있다면 그 문장만 짧게 나눠 연습해요.", "Mouth opening alone cannot tell us whether pronunciation is clear. Play this interval with sound. Keep your delivery if it is clear; if you need to replay a sentence, rehearse that sentence in short phrases."],
      brow_tension: ["같은 구간을 소리 없이 한 번, 소리와 함께 한 번 보세요. 전달하려던 느낌을 직접 고른 뒤 표정이 그 느낌과 맞는지 판단하세요.", "Watch once without sound, then with sound. Choose the intended feeling and compare the expression with it."],
      gaze: ["핵심 문장을 말할 때 카메라 부근에 시선이 머무는지 보세요. 시선 이동이 방해되는지는 영상과 전달 의도를 함께 보고 직접 판단하세요.", "Watch where the gaze rests during the key sentence. Judge distracting shifts yourself against the recording and intended delivery."],
    } as Record<string, [string,string]>)[finding.id]?.[ko ? 0 : 1] ?? (ko ? "실제 영상에서 바꿔 보고 싶은 행동 하나를 고르세요." : "Choose one delivery action from the actual recording.") };
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
