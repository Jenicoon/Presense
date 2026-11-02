import { measurementLabel } from "@/lib/measurement-labels";
import { findingText, localizedSummary, matchesLanguage, presentationSummary, findingGuidance } from "@/lib/report-locale";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { INFERENCE_URL, type LiveInferenceFrame } from "@/lib/live-signal";

export type ReportSegment = {
  modelVersion?: string;
  metricDefinitionVersion?: string;
  conceptDefinitionVersion?: string;
  segmentId: string;
  startMs: number;
  endMs: number;
  stressScore: number;
  predictionConfidence: number | null;
  concepts: Record<string, number>;
  audioFeatures: Record<string, number | string | boolean>;
  videoFeatures: Record<string, number | string | boolean>;
  quality: { faceDetected: boolean; audioValid: boolean };
};

export type AgentReport = {
  dataOrigin?: "recorded" | "synthetic" | "stressid";
  schemaVersion: string;
  language?: "ko" | "en";
  sessionId: string;
  modelVersion?: string;
  status: "complete" | "limited";
  summaryText: string;
  presenterSummary?: { ko: string; en: string };
  analysisStatus: string;
  observationReport?: {
    observedMs: number;
    coverage: number;
    averageStressScore: number | null;
    peakSegment: { startMs: number; endMs: number; stressScore: number; segmentId: string } | null;
    stressTimeline: Array<{ startMs: number; endMs: number; stressScore: number }>;
    concepts: Array<{ name: string; meanValue: number; observations: number }>;
    features: Array<{ id: string; label: string; meanValue: number; minValue: number; maxValue: number; observations: number; unit: string }>;
    patterns?: Array<{ id: string; label: string; startMs: number; endMs: number; value: number; comparisonValue: number; difference: number; unit: string; comparisonCount: number }>;
    modelWindowCount?: number;
    practiceFocus?: string;
    previousComparison?: { metricId: string; previousSessionId: string; previousSessionCount?: number; previousValue: number; currentValue: number; difference: number; unit: string; label: string } | null;
    phaseSummaries?: Array<{ startMs: number; endMs: number; observedMs: number; averageStressScore: number | null }>;
    peakConcepts?: Array<{ name: string; value: number; comparisonValue: number; difference: number }>;
    personalBaseline?: { score: number; sampleCount: number; averageDifference: number | null; peakDifference: number | null };
  };
  reflection?: {
    kind?: "peak" | "overall";
    segmentId: string;
    startMs: number;
    endMs: number;
    question: string;
    answer: "intentional" | "unintentional" | "unsure" | null;
  };
  observationEvidenceIds?: string[];
  rawSegments?: ReportSegment[];
  coachingAvailable?: boolean;
  coachingDisabledReason?: "dataset_privacy";
  previousCoaching?: { previousSessionId:string;goalLabel:string;comparable:boolean;lastOutcome:string|null };
  priorities: Array<{
    metric?: string;
    referenceValue?: number | null;
    modality?: string;
    independentObservations?: number;
    assessment?: { independentObservations: number };
    selectedSegmentIds?: string[];
    observationEvidenceComplete?: boolean;
    verifiedObservationCount?: number;
    observations?: Array<{segmentId: string; startMs: number; endMs: number; value: number; stressScore: number; conceptValues: Record<string,number>}>;
    id: string;
    label: string;
    observationText: string;
    recommendation: string;
    reviewAction: string;
    practiceSuggestion: string;
    evidenceIds?: string[];
    ranges: Array<{ startMs: number; endMs: number }>;
  }>;
  limitations: string[];
  evidence?: Array<{ id: string; title?: string | null; source: string; articleUrl?: string | null; doi?: string | null; findingKo?: string | null; page?: number | null; applicability?: "direct" | "related" }>;
  analysis: Record<string, unknown>;
  agentRun?: { stopReason: string; actions?: Array<{action: string; candidateId: string; segmentIds?: string[]}> };
  [key: string]: unknown;
};

/** Expand older, generic saved summaries using measurements already stored in the report. */
export function reportDisplaySummary(report: AgentReport, ko: boolean): string {
  if (report.analysis && Array.isArray(report.priorities)) return presentationSummary(report, ko);
  const original = localizedSummary(report, ko);
  if (!original.includes(ko ? "음성·영상 특징은 뚜렷한 구간 차이를 보이지 않았습니다" :
    "The measured audio and video features showed no clear interval difference")) return original;
  const observed = report.observationReport;
  const peak = observed?.peakSegment;
  if (!observed || !peak) return original;
  const time = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  };
  const interval = `${time(peak.startMs)}–${time(peak.endMs)}`;
  const mean = observed.averageStressScore;
  const scores = (observed.stressTimeline ?? []).map((item) => item.stressScore);
  const nearlyFlat = scores.length > 0 && Math.max(...scores) - Math.min(...scores) < .02;
  const sentences = [nearlyFlat
    ? ko ? `분석 구간의 모델 스트레스 점수는 대체로 ${Math.round(peak.stressScore * 100)}/100 안팎으로 비슷했습니다.` :
      `Model stress scores were similar across the observed intervals, near ${Math.round(peak.stressScore * 100)}/100.`
    : ko
    ? `${interval} 구간의 모델 스트레스 점수는 ${Math.round(peak.stressScore * 100)}/100으로 이번 발표에서 가장 높았습니다${mean == null ? "." : ` (분석 구간 평균 ${Math.round(mean * 100)}/100).`}`
    : `The model stress score peaked at ${Math.round(peak.stressScore * 100)}/100 in ${interval}${mean == null ? "." : ` (observed average ${Math.round(mean * 100)}/100).`}`];
  const phases = (observed.phaseSummaries ?? []).filter((phase) => phase.averageStressScore !== null &&
    phase.observedMs >= (phase.endMs - phase.startMs) / 2);
  if (phases.length >= 2) {
    const highest = phases.reduce((a, b) => (a.averageStressScore ?? 0) >= (b.averageStressScore ?? 0) ? a : b);
    const lowest = phases.reduce((a, b) => (a.averageStressScore ?? 0) <= (b.averageStressScore ?? 0) ? a : b);
    if (Math.round(((highest.averageStressScore ?? 0) - (lowest.averageStressScore ?? 0)) * 100) >= 2) {
      const labels = ko ? ["도입", "중반", "마무리"] : ["opening", "middle", "closing"];
      const rows = observed.phaseSummaries ?? [];
      sentences.push(ko
        ? `${labels[rows.indexOf(highest)]} 평균 ${Math.round((highest.averageStressScore ?? 0) * 100)}/100으로 ${labels[rows.indexOf(lowest)]} ${Math.round((lowest.averageStressScore ?? 0) * 100)}/100보다 높았습니다.`
        : `The ${labels[rows.indexOf(highest)]} averaged ${Math.round((highest.averageStressScore ?? 0) * 100)}/100, above the ${labels[rows.indexOf(lowest)]} at ${Math.round((lowest.averageStressScore ?? 0) * 100)}/100.`);
    }
  }
  const features = observed.features ?? [];
  const selected = ["pitch_change", "pitch_variability", "gaze"].map((id) => features.find((item) => item.id === id)).filter((item) => item !== undefined).slice(0, 2);
  if (selected.length) sentences.push((ko ? "음성·영상 특징의 구간 차이는 작았습니다. 발표 전체 관측 평균: " :
    "Audio and video features changed little across intervals. Observed session means: ") +
    selected.map((item) => `${item.label.split(" / ")[ko ? 0 : 1] || item.label} ${item.meanValue.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}`).join(" · ") + ".");
  const concept = observed.peakConcepts?.[0] ?? observed.concepts?.[0];
  if (concept) {
    if ("value" in concept) sentences.push(ko
      ? `같은 구간의 Concept 출력 ‘${measurementLabel(concept.name, ko)}’ 값은 ${concept.value.toFixed(2)} (다른 창 중앙값 ${concept.comparisonValue.toFixed(2)})였습니다.`
      : `The ${measurementLabel(concept.name, ko)} concept output there was ${concept.value.toFixed(2)} (other-window median ${concept.comparisonValue.toFixed(2)}).`);
    else sentences.push(ko
      ? `발표 전체에서 가장 크게 나온 Concept 출력은 ‘${measurementLabel(concept.name, ko)}’ 평균 ${concept.meanValue.toFixed(2)}이었습니다.`
      : `The largest session-wide concept output was ${measurementLabel(concept.name, ko)} at ${concept.meanValue.toFixed(2)} on average.`);
  }
  sentences.push(nearlyFlat ? (ko ? "전체 영상에서 실제 발화와 표정의 흐름을 확인해 보세요." :
    "Review the speech and expression across the recording.") :
    (ko ? `${interval} 구간의 실제 발화와 표정을 영상에서 확인해 보세요.` :
      `Review the actual speech and expression in ${interval} on the recording.`));
  return sentences.join(" ");
}

export function agentNextPractice(report: AgentReport, ko: boolean): string {
  const reflection = report.reflection;
  if (reflection?.kind === "overall" && reflection.answer === "intentional") return ko
    ? "의도한 전달 방식으로 기록했습니다. 영상을 다시 보며 목소리와 표정이 전달하려던 내용과 맞는지 확인해 보세요."
    : "Recorded as intended delivery. Replay the recording and check whether your voice and expression matched your intent.";
  if (reflection?.kind === "overall" && reflection.answer === "unintentional") return ko
    ? "다음 발표에서는 도입부를 짧게 다시 녹화하고, 말하는 속도와 목소리 크기를 의도한 수준으로 조정해 비교해 보세요."
    : "Record the opening again, adjust pace and volume toward your intent, and compare both takes.";
  if (reflection?.kind === "overall" && reflection.answer === "unsure") return ko
    ? "발표 영상을 도입·중반·마무리로 나눠 보며 속도·목소리 크기·표정이 전달 목표와 맞는지 확인하세요."
    : "Review the opening, middle, and closing for pace, volume, and expression against your delivery goal.";
  if (reflection?.answer === "intentional") {
    const unrelated = report.priorities.find((item) => !(item.ranges ?? []).some((range) =>
      range.startMs < reflection.endMs && range.endMs > reflection.startMs));
    const otherPractice = unrelated?.practiceSuggestion || unrelated?.reviewAction || unrelated?.recommendation;
    if (otherPractice && unrelated) return matchesLanguage(otherPractice, ko) ? otherPractice : findingText(unrelated, ko).practice;
    return ko
      ? "의도적으로 강조한 구간으로 기록했습니다. 영상을 보며 강조가 전달하려던 내용과 맞는지 확인하고, 다음 발표에서도 같은 의도를 유지해 보세요."
      : "Recorded as intentional emphasis. Review whether the delivery matched your intent, then try it again in the next take.";
  }
  if (reflection?.answer === "unintentional") return ko
    ? "다음 발표에서는 해당 구간 앞에서 잠깐 멈추고 호흡을 정리한 뒤 같은 문장을 다시 말해 보세요. 두 녹화의 전달 차이를 비교하세요."
    : "In the next take, pause and reset your breath before that interval. Compare how the same sentence comes across in both recordings.";
  if (reflection?.answer === "unsure") return ko
    ? "해당 영상을 다시 보며 목소리 크기·속도·표정이 전달하려던 내용과 맞는지 확인하세요. 점수만으로 의도를 판단하지 않습니다."
    : "Replay that interval and check whether volume, pace, and expression fit your intent. The score alone cannot tell.";
  if (report.analysis && report.priorities.length) return findingGuidance(report.priorities[0], ko).goal;
  if(report.priorities.length === 0) return Number(report.analysis?.coverage ?? 0)<.5
    ? (ko ? "분석 자료가 부족합니다. 카메라와 마이크를 확인한 뒤 관측 자료를 더 모아 주세요." : "Analysis data is limited. Check the camera and microphone and collect more observations.")
    : (ko ? "반복적으로 확인된 주요 문제가 없어 별도의 교정 과제를 만들지 않았습니다. 잘 유지한 부분은 영상과 함께 직접 확인하세요." : "No repeatedly observed major issue was found, so no corrective exercise was assigned. Review the recording to identify what you maintained well.");
  const finding = report.priorities.find((item) => item.practiceSuggestion || item.reviewAction || item.recommendation);
  const recommendation = finding?.practiceSuggestion || finding?.reviewAction || finding?.recommendation;
  if (recommendation && matchesLanguage(recommendation, ko)) return recommendation;
  if (finding) return findingText(finding, ko).practice;
  if (matchesLanguage(report.observationReport?.practiceFocus, ko)) return report.observationReport!.practiceFocus!;
  if (!report.observationReport?.peakSegment) {
    return ko ? "카메라와 마이크를 확인한 뒤 다시 발표를 녹화해 보세요." :
      "Check the camera and microphone, then record another presentation.";
  }
  return ko ? "모델 점수가 가장 높았던 구간의 실제 영상·음성을 확인하고, 같은 발표를 다시 녹화해 비교해 보세요." :
    "Review the recording at the highest model-score interval, then record the same talk again for comparison.";
}

export function agentReflectionInterpretation(report: AgentReport, ko: boolean): string | null {
  if (report.reflection?.kind === "overall") {
    if (report.reflection.answer === "intentional") return ko ? "의도한 전달 방식으로 기록했습니다. 모델 점수만으로 품질을 판단하지 않습니다." : "Recorded as intended delivery. The model score alone does not rate its quality.";
    if (report.reflection.answer === "unintentional") return ko ? "의도와 다른 전달로 기록했습니다. 아래 연습안을 확인하세요." : "Recorded as different from your intent. See the practice step below.";
    if (report.reflection.answer === "unsure") return ko ? "판단을 보류했습니다. 영상 확인 기준을 아래에 안내합니다." : "Intent remains undecided. Use the recording review guide below.";
  }
  switch (report.reflection?.answer) {
    case "intentional": return ko
      ? "의도한 강조로 기록했습니다. 이 점수만으로 문제 구간이라고 판단하지 않습니다."
      : "Recorded as intentional emphasis. The score alone does not make this a problem interval.";
    case "unintentional": return ko
      ? "의도하지 않은 변화로 기록했습니다. 아래에 다음 발표에서 해볼 연습을 제안합니다."
      : "Recorded as an unintentional change. The next practice step is shown below.";
    case "unsure": return ko
      ? "의도 판단을 보류했습니다. 영상에서 확인할 기준을 아래에 안내합니다."
      : "Intent remains undecided. Review the recording using the guide below.";
    default: return null;
  }
}

export function showPriorityAdvice(report: AgentReport, ranges: Array<{ startMs: number; endMs: number }>): boolean {
  const reflection = report.reflection;
  if (!reflection?.answer || reflection.kind === "overall") return true;
  return !ranges.some((range) => range.startMs < reflection.endMs && range.endMs > reflection.startMs);
}

function finiteNumbers(values: Record<string, unknown>): Record<string, number> {
  return Object.fromEntries(Object.entries(values).filter((entry): entry is [string, number] =>
    typeof entry[1] === "number" && Number.isFinite(entry[1])));
}

function finiteFeatures(values: Record<string, unknown>): Record<string, number | string | boolean> {
  return Object.fromEntries(Object.entries(values).filter((entry): entry is [string, number | string | boolean] =>
    typeof entry[1] === "string" || typeof entry[1] === "boolean" ||
    (typeof entry[1] === "number" && Number.isFinite(entry[1]))));
}

export function toReportSegment(frame: LiveInferenceFrame, index: number, endMs: number): ReportSegment {
  return {
    ...(frame.modelVersion ? {modelVersion:frame.modelVersion, metricDefinitionVersion:frame.metricDefinitionVersion, conceptDefinitionVersion:frame.conceptDefinitionVersion} : {}),
    segmentId: `capture-${index}`,
    startMs: Math.max(0, endMs - 10_000),
    endMs,
    stressScore: frame.stressScore,
    predictionConfidence: frame.confidence,
    concepts: finiteNumbers(frame.concepts ?? {}),
    audioFeatures: finiteFeatures(frame.audioFeatures ?? {}),
    videoFeatures: finiteFeatures(frame.videoFeatures ?? {}),
    quality: frame.quality ?? { faceDetected: false, audioValid: false },
  };
}

export async function generateAgentReport(input: {
  sessionId: string;
  durationMs: number;
  language: "ko" | "en";
  sceneLabel: string;
  segments: ReportSegment[];
  practiceContext?: { sessionId: string; practiceId: string };
  personalBaseline?: number;
  baselineSampleCount?: number;
  baselineModelVersion?: string;
}): Promise<AgentReport> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) throw new Error("보고서를 생성하려면 로그인해 주세요.");
  const { data: { session }, error } = await supabase.auth.getSession();
  if (error || !session?.access_token) throw new Error("로그인 세션을 확인할 수 없습니다.");
  const response = await fetch(`${INFERENCE_URL.replace(/\/$/, "")}/agent/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.access_token}` },
    body: JSON.stringify({ ...input, source: "live" }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(typeof payload.detail === "string" ? payload.detail : `보고서 생성 실패 (${response.status})`);
  }
  const report: unknown = await response.json();
  if (!report || typeof report !== "object" ||
      typeof (report as AgentReport).summaryText !== "string" ||
      !Array.isArray((report as AgentReport).priorities)) {
    throw new Error("보고서 응답 형식이 올바르지 않습니다.");
  }
  return report as AgentReport;
}
