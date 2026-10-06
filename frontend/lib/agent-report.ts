import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { INFERENCE_URL, type LiveInferenceFrame } from "@/lib/live-signal";

export type ReportSegment = {
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
  schemaVersion: string;
  sessionId: string;
  status: "complete" | "limited";
  summaryText: string;
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
  };
  observationEvidenceIds?: string[];
  priorities: Array<{
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
  agentRun?: { stopReason: string };
  [key: string]: unknown;
};

/** Expand older, generic saved summaries using measurements already stored in the report. */
export function reportDisplaySummary(report: AgentReport, ko: boolean): string {
  const original = report.summaryText;
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
      ? `같은 구간의 Concept 출력 ‘${concept.name}’ 값은 ${concept.value.toFixed(2)} (다른 창 중앙값 ${concept.comparisonValue.toFixed(2)})였습니다.`
      : `The ${concept.name} concept output there was ${concept.value.toFixed(2)} (other-window median ${concept.comparisonValue.toFixed(2)}).`);
    else sentences.push(ko
      ? `발표 전체에서 가장 크게 나온 Concept 출력은 ‘${concept.name}’ 평균 ${concept.meanValue.toFixed(2)}이었습니다.`
      : `The largest session-wide concept output was ${concept.name} at ${concept.meanValue.toFixed(2)} on average.`);
  }
  sentences.push(nearlyFlat ? (ko ? "전체 영상에서 실제 발화와 표정의 흐름을 확인해 보세요." :
    "Review the speech and expression across the recording.") :
    (ko ? `${interval} 구간의 실제 발화와 표정을 영상에서 확인해 보세요.` :
      `Review the actual speech and expression in ${interval} on the recording.`));
  return sentences.join(" ");
}

export function agentNextPractice(report: AgentReport, ko: boolean): string {
  const finding = report.priorities.find((item) => item.practiceSuggestion || item.reviewAction || item.recommendation);
  const recommendation = finding?.practiceSuggestion || finding?.reviewAction || finding?.recommendation;
  if (recommendation) return recommendation;
  if (report.observationReport?.practiceFocus) return report.observationReport.practiceFocus;
  if (!report.observationReport?.peakSegment) {
    return ko ? "카메라와 마이크를 확인한 뒤 다시 발표를 녹화해 보세요." :
      "Check the camera and microphone, then record another presentation.";
  }
  return ko ? "모델 점수가 가장 높았던 구간의 실제 영상·음성을 확인하고, 같은 발표를 다시 녹화해 비교해 보세요." :
    "Review the recording at the highest model-score interval, then record the same talk again for comparison.";
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
