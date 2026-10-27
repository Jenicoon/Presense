"use client";
import { useState } from "react";
import { ArrowRight, Clock3, Gauge, Layers3, ScanLine, Sparkles } from "lucide-react";
import { bilingualLabel, findingText } from "@/lib/report-locale";
import { AgentEvidence } from "@/components/agent-observation-report";
import type { AgentReport } from "@/lib/agent-report";
import { measurementLabel } from "@/lib/measurement-labels";
import { clock } from "@/lib/coaching";
export type TimelineCell = {
  startMs: number;
  endMs: number;
  stressScore: number | null;
};
export function withGaps(
  cells: TimelineCell[],
  durationMs: number,
): TimelineCell[] {
  const output: TimelineCell[] = [];
  let end = 0;
  for (const c of [...cells].sort((a, b) => a.startMs - b.startMs)) {
    if (c.startMs > end)
      output.push({ startMs: end, endMs: c.startMs, stressScore: null });
    output.push(c);
    end = c.endMs;
  }
  if (end < durationMs)
    output.push({ startMs: end, endMs: durationMs, stressScore: null });
  return output;
}
export function mergeTimeline(
  cells: TimelineCell[],
  durationMs: number,
): TimelineCell[] {
  if (cells.length <= 120) return cells;
  const result: TimelineCell[] = [];
  for (const c of cells) {
    const last = result[result.length - 1];
    if (
      last &&
      last.endMs === c.startMs &&
      last.stressScore !== null &&
      c.stressScore !== null &&
      c.endMs - last.startMs <= durationMs / 120
    ) {
      last.stressScore =
        (last.stressScore * (last.endMs - last.startMs) +
          c.stressScore * (c.endMs - c.startMs)) /
        (c.endMs - last.startMs);
      last.endMs = c.endMs;
    } else result.push({ ...c });
  }
  return result;
}
export function SessionAgentReport({ report, language, onSeek }: {
  report: AgentReport;
  language: "ko" | "en";
  onSeek?: (ms: number) => void;
}) {
  const ko = language === "ko";
  const [page, setPage] = useState(0);
  const a = report.analysis;
  const duration = Number(a.durationMs ?? 0);
  const original = (a.timeline ?? []) as TimelineCell[];
  const cells = withGaps(mergeTimeline(original, duration), duration);
  const peak = report.observationReport?.peakSegment;
  const raw = report.rawSegments ?? [];
  const first = report.priorities[0];
  const open = (findingId?: string) => window.dispatchEvent(new CustomEvent("presense:open-agent", {
    detail: { sessionId: report.sessionId, findingId },
  }));
  const stats = [
    { icon: Clock3, label: ko ? "실제 분석 시간" : "Time analyzed", value: `${(Number(a.observedMs ?? 0) / 1000).toFixed(0)}${ko ? "초" : "s"}`, note: ko ? `전체 ${(duration / 1000).toFixed(0)}초 중` : `of ${(duration / 1000).toFixed(0)}s total` },
    { icon: ScanLine, label: ko ? "분석 커버리지" : "Analysis coverage", value: `${Math.round(Number(a.coverage ?? 0) * 100)}%`, note: ko ? "자료가 있는 시간 기준" : "Time with usable data" },
    { icon: Layers3, label: ko ? "분석 구간" : "Usable intervals", value: `${Number(a.usableSegmentCount ?? 0)}`, note: ko ? `수집한 ${Number(a.segmentCount ?? 0)}개 중` : `of ${Number(a.segmentCount ?? 0)} collected` },
    { icon: Gauge, label: ko ? "평균 모델 점수" : "Mean model score", value: typeof a.averageStress === "number" ? a.averageStress.toFixed(3) : "—", note: typeof a.peakStress === "number" ? `${ko ? "최고" : "Peak"} ${a.peakStress.toFixed(3)}${peak ? ` · ${clock(peak.startMs)}` : ""}` : ko ? "분석 자료 없음" : "No analysis data" },
  ];
  return <section className="session-agent-report" aria-label={ko ? "세션 분석과 코칭" : "Session analysis and coaching"}>
    <div className="review-stats">
      {stats.map(({ icon: Icon, label, value, note }) => <div className="review-stat" key={label}>
        <div className="review-stat-label"><Icon size={14} />{label}</div>
        <strong>{value}</strong><span>{note}</span>
      </div>)}
    </div>
    <div className="review-next-step">
      <span className="review-next-icon"><Sparkles size={19} /></span>
      <div><span className="review-eyebrow">{ko ? "다음으로 할 일" : "Your next step"}</span>
        <h3>{first ? findingText(first, ko).label : ko ? "이번 발표 돌아보기" : "Review this presentation"}</h3>
        <p>{first ? (ko ? "먼저 근거 구간을 보고, 한 가지 목표로 짧게 연습해 보세요." : "Review the supporting interval, then try one short exercise.") : ko ? "영상을 보며 잘 유지한 부분을 확인해 보세요." : "Review the recording to see what you maintained well."}</p>
      </div>
      {report.coachingAvailable === false ? <p role="status">{ko ? "연결을 확인한 후 보고서를 다시 생성해 주세요." : "Check the connection and regenerate the report."}</p> :
        <button type="button" className="btn btn-primary" onClick={() => open(first?.id)}>{first ? (ko ? "코칭 시작" : "Start coaching") : ko ? "코치와 살펴보기" : "Review with coach"}<ArrowRight size={15} /></button>}
    </div>
    {report.previousCoaching && <p className="review-context">{ko ? "이전 목표" : "Previous goal"} · {bilingualLabel(report.previousCoaching.goalLabel, ko, ko ? "저장된 연습 목표" : "Saved practice goal")}{!report.previousCoaching.comparable && (ko ? " · 분석 조건이 달라 수치 비교를 보류합니다." : " · Analysis conditions differ; numerical comparison is unavailable.")}</p>}
    <section className="review-section review-timeline">
      <div className="review-section-heading"><div><h3>{ko ? "시간별 모델 스트레스 신호" : "Model stress signal over time"}</h3><p>{ko ? "구간을 선택해 당시의 발표를 확인하세요." : "Select an interval to review that moment."}</p></div><span className="review-scale">{ko ? "0–1 분석 점수" : "0–1 analysis score"}</span></div>
      <figure className="stress-line-chart">
        <svg
          viewBox="0 0 650 220"
          role="img"
          aria-label={
            ko ? "실제 관측 구간별 모델 점수" : "Model scores at observed times"
          }
        >
          {[0, 0.25, 0.5, 0.75, 1].map((v) => (
            <g key={v}>
              <line
                x1="40"
                x2="630"
                y1={180 - v * 160}
                y2={180 - v * 160}
                className="stress-line-grid"
              />
              <text x="4" y={184 - v * 160} className="stress-line-label">
                {v}
              </text>
            </g>
          ))}
          {cells.map((c, i) =>
            c.stressScore === null ? (
              <rect
                key={i}
                x={40 + (c.startMs / Math.max(duration, 1)) * 590}
                y="20"
                width={((c.endMs - c.startMs) / Math.max(duration, 1)) * 590}
                height="160"
                fill="var(--border)"
                opacity=".35"
              >
                <title>
                  {clock(c.startMs)}–{clock(c.endMs)} ·{" "}
                  {ko ? "분석 자료 없음" : "No analysis data"}
                </title>
              </rect>
            ) : (
              <line
                key={i}
                x1={40 + (c.startMs / Math.max(duration, 1)) * 590}
                x2={40 + (c.endMs / Math.max(duration, 1)) * 590}
                y1={180 - c.stressScore * 160}
                y2={180 - c.stressScore * 160}
                className="stress-line-path"
              />
            ),
          )}
          <text x="40" y="210" className="stress-line-label">
            00:00
          </text>
          <text x="580" y="210" className="stress-line-label">
            {clock(duration)}
          </text>
        </svg>
      </figure>
      <div className="video-timeline actual-timeline">
        {cells.map((c, i) => (
          <button
            key={i}
            type="button"
            disabled={c.stressScore === null || !onSeek}
            className={
              c.stressScore === null
                ? "gap"
                : c.stressScore >= 0.7
                  ? "high"
                  : c.stressScore >= 0.5
                    ? "mid"
                    : "low"
            }
            style={{ flex: c.endMs - c.startMs }}
            onClick={() => onSeek?.(c.startMs)}
            title={`${clock(c.startMs)}–${clock(c.endMs)} · ${c.stressScore === null ? (ko ? "분석 자료 없음" : "No analysis data") : c.stressScore.toFixed(3)}`}
            aria-label={`${clock(c.startMs)}–${clock(c.endMs)} ${c.stressScore === null ? (ko ? "분석 자료 없음" : "No analysis data") : c.stressScore.toFixed(3)}`}
          />
        ))}
      </div>

      <div className="review-timeline-key"><span><i />{ko ? "관측된 모델 점수" : "Observed model score"}</span><span><i className="gap" />{ko ? "분석 자료 없음" : "No analysis data"}</span></div>
      <details className="review-details review-method"><summary>{ko ? "타임라인 읽는 법" : "How to read the timeline"}</summary><p>{ko ? "회색은 분석 자료가 없는 시간입니다. 겹친 시간은 한 번만 반영하고, 같은 시점의 점수는 평균합니다. 낮은 점수도 모두 표시합니다. 도입·전개·핵심·마무리는 시간 표시 구간입니다." : "Gray marks time without analysis data. Overlap counts once; concurrent scores are averaged. Low scores remain visible. Open / Build / Core / Close are time divisions for display."}</p>{original.length > 120 && <p>{ko ? "많은 관측은 묶어 표시하며 원본은 아래에서 확인할 수 있습니다." : "Dense observations are grouped for display. Original results are available below."}</p>}</details>
    </section>
    <section className="review-findings"><div className="review-section-heading"><div><h3>{ko ? "주요 발견" : "Key findings"}</h3><p>{ko ? "반복된 관측과 실제 측정값을 함께 살펴보세요." : "Review repeated observations alongside the measurements."}</p></div><span className="review-count">{report.priorities.length}</span></div>
    {report.priorities.length === 0 ? <div className="review-empty"><ScanLine size={21} /><p>{Number(a.coverage ?? 0) < 0.5 ? (ko ? "분석 자료가 부족해 주요 문제를 판단하지 않았습니다." : "Insufficient analysis data to judge major issues.") : ko ? "이번 세션에서는 반복적으로 확인된 주요 문제를 찾지 못했습니다." : "No repeatedly observed major issue was found in this session."}</p></div> : report.priorities.slice(0, 3).map((f, index) => {
      const text = findingText(f, ko);
      return <article key={f.id} className="review-finding">
        <div className="review-finding-heading"><span className="review-finding-number">{String(index + 1).padStart(2, "0")}</span><h4>{text.label}</h4><span className="review-finding-count">{ko ? "독립 관측" : "Independent observations"} {f.independentObservations ?? f.assessment?.independentObservations ?? "—"}{ko ? "회" : ""}</span></div>
        <p className="review-finding-summary">{text.observation}</p>
        <div className="review-observations">{f.observations?.map(o => <div className="review-observation" key={o.segmentId}>
          <button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(o.startMs)}>▶ {clock(o.startMs)}–{clock(o.endMs)}</button>
          <span>{measurementLabel(f.metric ?? "", ko)}<strong>{Number(o.value.toFixed(2))}</strong></span>
          <span>{ko ? "모델 점수" : "Model score"}<strong>{o.stressScore.toFixed(3)}</strong></span>
        </div>)}</div>
        <div className="review-finding-action"><div><strong>{ko ? "영상에서 확인할 것" : "What to check"}</strong><p>{text.review}</p></div><div><strong>{ko ? "다음 연습" : "Next exercise"}</strong><p>{text.practice}</p></div></div>
        <details className="review-details"><summary>{ko ? "관련 패턴 값과 참고 근거" : "Related patterns and sources"}</summary>{f.observations?.map(o => <p key={o.segmentId}>{clock(o.startMs)}–{clock(o.endMs)} · {Object.entries(o.conceptValues).map(([k, v]) => `${measurementLabel(k, ko)} ${v.toFixed(3)}`).join(" · ")}</p>)}<AgentEvidence report={report} ids={f.evidenceIds} ko={ko} /></details>
        <button type="button" className="btn btn-outline" onClick={() => open(f.id)}>{ko ? "코치와 이 부분 연습하기" : "Practice this with the coach"}<ArrowRight size={14} /></button>
      </article>;
    })}</section>
    {raw.length > 0 && <details className="review-details review-raw"><summary>{ko ? `실제 분석 결과 ${raw.length}개 확인` : `Inspect ${raw.length} original analysis windows`}</summary><div className="observation-table-wrap"><table className="review-raw-table"><thead><tr><th>{ko ? "구간" : "Interval"}</th><th>{ko ? "모델 점수" : "Model score"}</th><th>{ko ? "분석 신뢰도" : "Confidence"}</th><th>{ko ? "자료 상태" : "Data quality"}</th></tr></thead><tbody>{raw.slice(page * 30, (page + 1) * 30).map(s => <tr key={s.segmentId}><td>{clock(s.startMs)}–{clock(s.endMs)}</td><td>{s.stressScore.toFixed(3)}</td><td>{s.predictionConfidence?.toFixed(3) ?? "—"}</td><td>{s.quality.audioValid ? (ko ? "음성 유효" : "Audio valid") : ko ? "음성 자료 부족" : "Audio unavailable"} · {s.quality.faceDetected ? (ko ? "얼굴 검출" : "Face detected") : ko ? "얼굴 자료 부족" : "Face unavailable"}</td></tr>)}</tbody></table></div>{raw.length > 30 && <div className="review-pagination"><button className="btn btn-outline" disabled={page === 0} onClick={() => setPage(p => p - 1)}>{ko ? "이전" : "Previous"}</button><span>{page + 1} / {Math.ceil(raw.length / 30)}</span><button className="btn btn-outline" disabled={(page + 1) * 30 >= raw.length} onClick={() => setPage(p => p + 1)}>{ko ? "다음" : "Next"}</button></div>}</details>}
  </section>;
}
