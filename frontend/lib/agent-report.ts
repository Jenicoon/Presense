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
  evidence?: Array<{ id: string; title?: string | null; source: string; articleUrl?: string | null; doi?: string | null; findingKo?: string | null }>;
  analysis: Record<string, unknown>;
  agentRun?: { stopReason: string };
  [key: string]: unknown;
};

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
