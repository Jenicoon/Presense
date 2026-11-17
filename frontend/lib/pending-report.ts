import type { AgentReport, ReportRequest } from "@/lib/agent-report";
import { summarizeWindows, observedTimeline } from "@/lib/report-windows";

export function pendingSessionReport(input: ReportRequest): AgentReport {
  const cells = summarizeWindows(input.segments, input.durationMs);
  const observedMs = cells.reduce((sum, row) => sum + row.observedMs, 0);
  const weighted = cells.reduce((sum, row) => sum + (row.score ?? 0) * row.observedMs, 0);
  const first = input.segments[0];
  const { segments, ...reportInput } = input;
  return {
    schemaVersion: "1.1", sessionId: input.sessionId, language: input.language,
    modelVersion: first?.modelVersion, metricDefinitionVersion: first?.metricDefinitionVersion,
    conceptDefinitionVersion: first?.conceptDefinitionVersion,
    status: "limited", analysisStatus: "pending", synthesisStatus: "unavailable",
    generationState: "pending", reportInput,
    summaryText: input.language === "ko" ? "발표 기록을 저장했습니다. 보고서를 준비하고 있어요." : "Your session is saved. The report is being prepared.",
    analysis: { durationMs: input.durationMs, observedMs, coverage: observedMs / input.durationMs,
      averageStress: observedMs ? weighted / observedMs : null,
      timeline: observedTimeline(segments, input.durationMs) },
    rawSegments: segments, priorities: [], limitations: [], coachingAvailable: false,
  };
}
export function savedReportInput(report: AgentReport): ReportRequest | null {
  if (!report.reportInput || !report.rawSegments) return null;
  return { ...(report.reportInput as Omit<ReportRequest, "segments">), segments: report.rawSegments };
}
