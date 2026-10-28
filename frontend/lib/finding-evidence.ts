import type { AgentReport } from "@/lib/agent-report";

/** Restore only exact IDs saved by the analysis action; never fill merged ranges. */
export function completeReportEvidence(report: AgentReport): AgentReport {
  if (!report.rawSegments?.length) return report;
  const raw = new Map(report.rawSegments.map(row => [row.segmentId, row]));
  return {...report, priorities: report.priorities.map(finding => {
    const {modality, metric} = finding;
    if (!modality || !metric) return finding;
    const action = [...(report.agentRun?.actions ?? [])].reverse().find(row => row.action === "analyze_segment" && row.candidateId === finding.id && row.segmentIds?.length);
    const ids = finding.selectedSegmentIds ?? action?.segmentIds ?? finding.observations?.map(row => row.segmentId) ?? [];
    const selected = [...new Set(ids)].flatMap(id => {
      const row = raw.get(id);
      if (!row) return [];
      const valid = modality === "audio" ? row.quality.audioValid : modality === "video" ? row.quality.faceDetected : modality === "concept" && row.quality.audioValid && row.quality.faceDetected;
      const values = modality === "audio" ? row.audioFeatures : modality === "video" ? row.videoFeatures : row.concepts;
      const value = values[metric];
      if (!valid || typeof value !== "number" || !Number.isFinite(value) || (metric === "f0_mean" && value <= 0) || (metric === "f0_std" && value < 0)) return [];
      return [{segmentId: row.segmentId, startMs: row.startMs, endMs: row.endMs, value, stressScore: row.stressScore, conceptValues: row.quality.audioValid && row.quality.faceDetected ? row.concepts : {}}];
    }).sort((a,b) => a.endMs-b.endMs || a.startMs-b.startMs);
    const independent: typeof selected = [];
    for (const row of selected) if (!independent.length || row.startMs >= independent[independent.length-1].endMs) independent.push(row);
    return {...finding, selectedSegmentIds: [...new Set(ids)], observations: independent, verifiedObservationCount: independent.length, observationEvidenceComplete: independent.length === (finding.independentObservations ?? independent.length)};
  })};
}
