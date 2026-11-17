"use client";
import { useState } from "react";
import Link from "next/link";
import type { ReportSegment } from "@/lib/agent-report";
import { reviewIntervals } from "@/lib/report-windows";
import { clock } from "@/lib/coaching";

export function SessionIntervalReview({ sessionId, segments, durationMs, videoUrl, ko, onSeek, pauseReportVideo, practiceHref }: {
  sessionId: string; segments: ReportSegment[]; durationMs: number; videoUrl?: string; ko: boolean;
  onSeek?: (ms: number) => void; pauseReportVideo?: () => void;
  practiceHref?: string;
}) {
  const intervals = reviewIntervals(segments, durationMs);
  const [selectedId, setSelectedId] = useState("");
  const selected = intervals.find(row => row.segmentId === selectedId) ?? intervals.reduce<ReportSegment | null>((best, row) => !best || row.stressScore > best.stressScore ? row : best, null);
  if (!selected) return <section className="review-section"><h3>{ko ? "구간 다시 보기" : "Replay an interval"}</h3><p>{ko ? "재생할 수 있는 분석 구간이 아직 없습니다." : "No analyzed interval is available to replay yet."}</p></section>;
  return <section className="review-section">
    <h3>{ko ? "관측 구간 다시 보기" : "Replay observed intervals"}</h3>
    <div className="review-practice-actions">
      <label>{ko ? "다시 볼 구간 " : "Choose an interval "}<select value={selected.segmentId} onChange={event => { setSelectedId(event.target.value); pauseReportVideo?.(); }}>
        {intervals.map(row => <option key={row.segmentId} value={row.segmentId}>{clock(row.startMs)}–{clock(row.endMs)}</option>)}
      </select></label>
      <button type="button" className="btn btn-outline" disabled={!onSeek} onClick={() => onSeek?.(selected.startMs)}>{ko ? "이 구간 재생" : "Play this interval"}</button>
      {!videoUrl && practiceHref && <Link className="btn btn-outline" href={`${practiceHref}&at=${selected.startMs}`}>{ko ? "영상 열고 연습하기" : "Open video and rehearse"}</Link>}
    </div>
    {!videoUrl && !practiceHref && <p>{ko ? "저장된 원본 영상이 있어야 구간 재생과 재녹화 비교를 할 수 있습니다." : "A saved original video is required to replay and compare takes."}</p>}
  </section>;
}
