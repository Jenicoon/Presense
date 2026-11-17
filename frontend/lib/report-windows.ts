import type { ReportSegment } from "@/lib/agent-report";

export type WindowSummary = { startMs: number; endMs: number; score: number | null; count: number; observedMs: number };
export function observedTimeline(rows: ReportSegment[], durationMs: number) {
  const usable = rows.filter(row => row.startMs >= 0 && row.endMs > row.startMs && row.endMs <= durationMs
    && Number.isFinite(row.stressScore) && row.stressScore >= 0 && row.stressScore <= 1
    && row.quality.audioValid && row.quality.faceDetected);
  const boundaries = [...new Set([0, durationMs, ...usable.flatMap(row => [row.startMs, row.endMs])])].sort((a,b) => a-b);
  return boundaries.slice(1).map((endMs, index) => {
    const startMs = boundaries[index];
    const active = usable.filter(row => row.startMs < endMs && row.endMs > startMs);
    return { startMs, endMs, stressScore: active.length ? active.reduce((sum, row) => sum + row.stressScore, 0) / active.length : null };
  }).filter(row => row.endMs > row.startMs);
}

/** One real recording interval per 30 seconds; retain the peak interval too. */
export function reviewIntervals(rows: ReportSegment[], durationMs: number) {
  const valid = rows.filter(row => row.startMs >= 0 && row.endMs > row.startMs && row.endMs <= durationMs
    && Number.isFinite(row.stressScore) && row.stressScore >= 0 && row.stressScore <= 1
    && row.quality.audioValid && row.quality.faceDetected).sort((a,b) => a.startMs-b.startMs);
  const representatives = new Map<number, ReportSegment>();
  for (const row of valid) if (!representatives.has(Math.floor(row.startMs / 30000))) representatives.set(Math.floor(row.startMs / 30000), row);
  const peak = valid.reduce<ReportSegment | null>((best, row) => !best || row.stressScore > best.stressScore ? row : best, null);
  const intervals = [...representatives.values()];
  if (peak && !intervals.includes(peak)) intervals.push(peak);
  return intervals.sort((a,b) => a.startMs-b.startMs);
}
/** Integrate each instant once, averaging simultaneous valid observations. */
export function summarizeWindows(rows: ReportSegment[], durationMs: number, binMs = 30_000): WindowSummary[] {
  if (!(durationMs > 0) || !(binMs > 0)) return [];
  const usable = rows.filter(row => row.endMs > row.startMs && Number.isFinite(row.stressScore)
    && row.stressScore >= 0 && row.stressScore <= 1 && row.quality.audioValid && row.quality.faceDetected);
  const output: WindowSummary[] = [];
  for (let startMs = 0; startMs < durationMs; startMs += binMs) {
    const endMs = Math.min(startMs + binMs, durationMs);
    const overlapping = usable.filter(row => row.startMs < endMs && row.endMs > startMs);
    const boundaries = [...new Set([startMs, endMs, ...overlapping.flatMap(row =>
      [Math.max(startMs, row.startMs), Math.min(endMs, row.endMs)])])].sort((a,b) => a-b);
    let weighted = 0, observedMs = 0;
    for (let i = 1; i < boundaries.length; i++) {
      const active = overlapping.filter(row => row.startMs < boundaries[i] && row.endMs > boundaries[i-1]);
      if (!active.length) continue;
      const elapsed = boundaries[i] - boundaries[i-1];
      observedMs += elapsed;
      weighted += elapsed * active.reduce((sum, row) => sum + row.stressScore, 0) / active.length;
    }
    output.push({ startMs, endMs, score: observedMs ? weighted / observedMs : null, count: overlapping.length, observedMs });
  }
  return output;
}
