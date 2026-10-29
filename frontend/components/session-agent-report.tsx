"use client";
import { useEffect, useState } from "react";
import { ArrowRight, Clock3, Gauge, Layers3, ScanLine, Sparkles } from "lucide-react";
import { bilingualLabel, findingText, findingGuidance, signalScore } from "@/lib/report-locale";
import { StressChart } from "@/components/stress-chart";
import { AgentEvidence } from "@/components/agent-observation-report";
import type { AgentReport } from "@/lib/agent-report";
import { completeReportEvidence } from "@/lib/finding-evidence";
import { measurementLabel } from "@/lib/measurement-labels";
import { clock, restoreCoach } from "@/lib/coaching";
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
/** Use the same real-time axis and gap handling in the original dashboard. */
export function ReportStressChart({ report, language, onSeek }: {
  report: AgentReport; language: "ko" | "en"; onSeek?: (ms: number) => void;
}) {
  const duration = Number(report.analysis.durationMs ?? 0);
  const cells = withGaps(mergeTimeline((report.analysis.timeline ?? []) as TimelineCell[], duration), duration);
  return <StressChart cells={cells} durationMs={duration} language={language} onSelect={onSeek} />;
}

export function SessionAgentReport({ report, language, onSeek, showTimeline = true }: {
  report: AgentReport;
  language: "ko" | "en";
  onSeek?: (ms: number) => void;
  showTimeline?: boolean;
}) {
  report = completeReportEvidence(report);
  const ko = language === "ko";
  const [page, setPage] = useState(0);
  const [hasSavedCoaching, setHasSavedCoaching] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const refresh = () => void restoreCoach(report.sessionId, language).then(data => {
      if (!cancelled) setHasSavedCoaching(data.messages.length > 0);
    }).catch(() => undefined);
    refresh();
    window.addEventListener("presense:coach-changed", refresh);
    return () => { cancelled = true; window.removeEventListener("presense:coach-changed", refresh); };
  }, [report.sessionId, language]);
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
    { icon: Gauge, label: ko ? "평균 스트레스 신호" : "Mean stress signal", value: signalScore(a.averageStress), note: typeof a.peakStress === "number" ? `${ko ? "최고" : "Peak"} ${Math.round(a.peakStress * 100)}${peak ? ` · ${clock(peak.startMs)}` : ""}` : ko ? "분석 자료 없음" : "No analysis data" },
  ];
  return <section className="session-agent-report" aria-label={ko ? "세션 분석과 코칭" : "Session analysis and coaching"}>
    {report.dataOrigin === "stressid" && <p className="review-context" role="status">{ko ? "StressID 예시 영상을 기기 내 모델로 분석한 결과입니다. 이 자료는 외부 AI 코칭에 전송하지 않습니다." : "This StressID example was analyzed by the local model. Its data is not sent to external AI coaching."}</p>}
    {report.dataOrigin === "synthetic" && <p className="review-context" role="status">{ko ? "합성 예시 분석 자료입니다." : "This analysis uses synthetic sample data."}</p>}
    <div className="review-stats">
      {stats.map(({ icon: Icon, label, value, note }) => <div className="review-stat" key={label}>
        <div className="review-stat-label"><Icon size={14} />{label}</div>
        <strong>{value}</strong><span>{note}</span>
      </div>)}
    </div>
    <details className="review-details review-score-explainer"><summary>{ko ? "스트레스 신호 점수는 무엇인가요?" : "What does the stress signal score mean?"}</summary><p>{ko ? "AI가 음성·영상에서 학습한 스트레스 관련 패턴을 얼마나 강하게 감지했는지 0–100으로 표시합니다. 같은 발표에서 다시 볼 구간을 찾고, 같은 조건의 재촬영과 비교하는 참고 자료입니다. 70점이 실제 스트레스 70%라는 뜻은 아니며, 발표 실력의 성적도 아닙니다. 평균은 실제 분석된 시간만 반영합니다." : "This 0–100 score shows how strongly the AI detected learned stress-related patterns in audio and video. Use it to find intervals to review and compare takes under the same conditions. A score of 70 does not mean 70% actual stress or grade your presentation. The mean includes analyzed time only."}</p></details>
    <div className="review-next-step">
      <span className="review-next-icon"><Sparkles size={19} /></span>
      <div><span className="review-eyebrow">{ko ? "다음으로 할 일" : "Your next step"}</span>
        <h3>{first ? findingGuidance(first, ko).title : ko ? "이번 발표 돌아보기" : "Review this presentation"}</h3>
        <p>{first ? (ko ? "영상을 보고 확인 결과를 선택하면, 그에 맞는 짧은 연습으로 이어집니다." : "Review the recording and select what you noticed to start a matching short exercise.") : ko ? "영상을 보며 잘 유지한 부분을 확인해 보세요." : "Review the recording to see what you maintained well."}</p>
      </div>
      {report.coachingAvailable === false ? <p role="status">{report.coachingDisabledReason === "dataset_privacy" ? (ko ? "예시 영상은 직접 살펴볼 수 있습니다. AI 코칭은 직접 촬영한 발표에서 이용해 주세요." : "Review this example locally. Use your own recording for AI coaching.") : (ko ? "연결을 확인한 후 보고서를 다시 생성해 주세요." : "Check the connection and regenerate the report.")}</p> :
        <button type="button" className="btn btn-primary" onClick={() => open(first?.id)}>{hasSavedCoaching ? (ko ? "저장된 코칭 이어가기" : "Continue saved coaching") : first ? (ko ? "이 구간 함께 확인하기" : "Review this interval together") : ko ? "코치와 살펴보기" : "Review with coach"}<ArrowRight size={15} /></button>}
    </div>
    {report.previousCoaching && <p className="review-context">{ko ? "이전 목표" : "Previous goal"} · {bilingualLabel(report.previousCoaching.goalLabel, ko, ko ? "저장된 연습 목표" : "Saved practice goal")}{!report.previousCoaching.comparable && (ko ? " · 분석 조건이 달라 수치 비교를 보류합니다." : " · Analysis conditions differ; numerical comparison is unavailable.")}</p>}
    {showTimeline && <div className="review-timeline-layout">
    <section className="review-section review-timeline">
      <div className="panel-head"><div className="panel-head-left"><h3 className="panel-title">{ko ? "세션 스트레스 신호 타임라인" : "Session Stress Signal Timeline"}</h3><span className="panel-subtitle">{ko ? "발표 후 전체 흐름" : "Post-session overview"}</span></div><Layers3 size={16} color="var(--text-secondary)" /></div>
      <StressChart cells={cells} durationMs={duration} language={language} onSelect={onSeek} />
      <details className="review-details review-timeline-intervals"><summary>{ko ? "구간별 점수 모두 보기" : "View all interval scores"}</summary>
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
            title={`${clock(c.startMs)}–${clock(c.endMs)} · ${c.stressScore === null ? (ko ? "분석 자료 없음" : "No analysis data") : signalScore(c.stressScore)}`}
            aria-label={`${clock(c.startMs)}–${clock(c.endMs)} ${c.stressScore === null ? (ko ? "분석 자료 없음" : "No analysis data") : signalScore(c.stressScore)}`}
          />
        ))}
      </div>

      </details>
      <div className="review-timeline-key"><span><i />{ko ? "관측된 스트레스 신호" : "Observed stress signal"}</span><span><i className="gap" />{ko ? "분석 자료 없음" : "No analysis data"}</span></div>
      <details className="review-details review-method"><summary>{ko ? "타임라인 읽는 법" : "How to read the timeline"}</summary><p>{ko ? "회색은 분석 자료가 없는 시간입니다. 겹친 시간은 한 번만 반영하고, 같은 시점의 점수는 평균합니다. 낮은 점수도 모두 표시합니다. 도입·전개·핵심·마무리는 시간 표시 구간입니다." : "Gray marks time without analysis data. Overlap counts once; concurrent scores are averaged. Low scores remain visible. Open / Build / Core / Close are time divisions for display."}</p>{original.length > 120 && <p>{ko ? "많은 관측은 묶어 표시하며 원본은 아래에서 확인할 수 있습니다." : "Dense observations are grouped for display. Original results are available below."}</p>}</details>
    </section>
    <aside className="review-section review-timeline-aside" aria-label={ko ? "발표 분석 요약" : "Presentation analysis summary"}>
      <div className="panel-head"><div className="panel-head-left"><h3 className="panel-title">{ko ? "발표 분석" : "Presentation Analysis"}</h3><span className="panel-subtitle">{ko ? "이번 세션에서 확인할 것" : "What to review"}</span></div><Sparkles size={16} color="var(--text-secondary)" /></div>
      <div className="coach-stack">
        <div className={`coach-card ${first ? "coach-alert" : "coach-ok"}`}><h4>{ko ? "확인할 부분" : "Review focus"}</h4><p>{first ? findingGuidance(first, ko).observation : Number(a.coverage ?? 0) < .5 ? (ko ? "분석 자료가 부족해 주요 문제를 판단하지 않았습니다." : "Insufficient data to judge major issues.") : (ko ? "반복적으로 확인된 주요 문제를 찾지 못했습니다." : "No repeatedly observed major issue was found.")}</p>{first?.observations?.[0] && onSeek && <button type="button" className="review-time-link" onClick={() => onSeek(first.observations![0].startMs)}>{ko ? "근거 영상 보기" : "View supporting video"}<ArrowRight size={13} /></button>}</div>
        <div className="coach-card coach-data"><h4>{ko ? "스트레스 신호가 가장 높았던 구간" : "Peak stress signal"}</h4><p>{typeof a.peakStress === "number" ? signalScore(a.peakStress) : (ko ? "분석 자료 없음" : "No analysis data")}{peak && <><br /><button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(peak.startMs)}>{clock(peak.startMs)}–{clock(peak.endMs)}{onSeek && <ArrowRight size={13} />}</button></>}</p></div>
      </div>
    </aside>
    </div>}
    <section className="review-findings"><div className="review-section-heading"><div><h3>{ko ? "함께 확인할 부분" : "What to review together"}</h3><p>{ko ? "반복된 관측과 실제 측정값을 함께 살펴보세요." : "Review repeated observations alongside the measurements."}</p></div><span className="review-count">{report.priorities.length}</span></div>
    {report.priorities.length === 0 ? <div className="review-empty"><ScanLine size={21} /><p>{Number(a.coverage ?? 0) < 0.5 ? (ko ? "분석 자료가 부족해 주요 문제를 판단하지 않았습니다." : "Insufficient analysis data to judge major issues.") : ko ? "이번 세션에서는 반복적으로 확인된 주요 문제를 찾지 못했습니다." : "No repeatedly observed major issue was found in this session."}</p></div> : report.priorities.slice(0, 3).map((f, index) => {
      const text = findingText(f, ko);
      const view = findingGuidance(f, ko);
      return <article key={f.id} className="review-finding">
        <div className="review-finding-heading"><span className="review-finding-number">{String(index + 1).padStart(2, "0")}</span><h4>{view.title}</h4><span className="review-finding-count">{ko ? `확인할 영상 ${f.observations?.length ?? 0}곳` : `${f.observations?.length ?? 0} intervals to review`}</span></div>
        <p className="review-finding-summary">{view.observation}</p>
        <div className="review-supporting-times" role="group" aria-label={ko ? "근거가 된 관측 구간" : "Supporting observation intervals"}>{f.observations?.map((o, n) => <button key={o.segmentId} type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(o.startMs)}>{n + 1}. {clock(o.startMs)}–{clock(o.endMs)}</button>)}</div>
        <details className="review-details"><summary>{ko ? "관측 근거와 측정값 보기" : "Observation evidence"}</summary><p>{text.observation}</p><p>{ko ? `서로 겹치지 않는 분석 ${f.independentObservations ?? f.assessment?.independentObservations ?? "—"}개를 근거로 선택했습니다.` : `Selected using ${f.independentObservations ?? f.assessment?.independentObservations ?? "—"} non-overlapping observations.`}</p><div className="review-observations">{f.observations?.map(o => <div className="review-observation" key={o.segmentId}>
          <button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(o.startMs)}>▶ {clock(o.startMs)}–{clock(o.endMs)}</button>
          <span>{measurementLabel(f.metric ?? "", ko)}<strong>{Number(o.value.toFixed(2))}</strong></span>
          <span>{ko ? "스트레스 신호 점수" : "Stress signal score"}<strong>{signalScore(o.stressScore)}</strong></span>
        </div>)}</div></details>
        <div className="review-finding-action"><div><strong>{ko ? "영상에서 확인할 것" : "What to check"}</strong><p>{view.question}</p></div><div><strong>{ko ? "다음 연습" : "Next exercise"}</strong><p>{view.goal}</p></div></div>
        <details className="review-details"><summary>{ko ? "관련 패턴 값과 참고 근거" : "Related patterns and sources"}</summary>{f.observations?.map(o => <p key={o.segmentId}>{clock(o.startMs)}–{clock(o.endMs)} · {Object.entries(o.conceptValues).map(([k, v]) => `${measurementLabel(k, ko)} ${v.toFixed(3)}`).join(" · ")}</p>)}<AgentEvidence report={report} ids={f.evidenceIds} ko={ko} /></details>
        <button type="button" className="btn btn-outline" disabled={report.coachingAvailable === false} onClick={() => open(f.id)}>{ko ? "이 구간 함께 확인하기" : "Review this interval together"}<ArrowRight size={14} /></button>
      </article>;
    })}</section>
    {raw.length > 0 && <details className="review-details review-raw"><summary>{ko ? `실제 분석 결과 ${raw.length}개 확인` : `Inspect ${raw.length} original analysis windows`}</summary><div className="observation-table-wrap"><table className="review-raw-table"><thead><tr><th>{ko ? "구간" : "Interval"}</th><th>{ko ? "스트레스 신호 점수" : "Stress signal score"}</th><th>{ko ? "분석 신뢰도" : "Confidence"}</th><th>{ko ? "자료 상태" : "Data quality"}</th></tr></thead><tbody>{raw.slice(page * 30, (page + 1) * 30).map(s => <tr key={s.segmentId}><td>{clock(s.startMs)}–{clock(s.endMs)}</td><td>{signalScore(s.stressScore)}</td><td>{s.predictionConfidence?.toFixed(3) ?? "—"}</td><td>{s.quality.audioValid ? (ko ? "음성 유효" : "Audio valid") : ko ? "음성 자료 부족" : "Audio unavailable"} · {s.quality.faceDetected ? (ko ? "얼굴 검출" : "Face detected") : ko ? "얼굴 자료 부족" : "Face unavailable"}</td></tr>)}</tbody></table></div>{raw.length > 30 && <div className="review-pagination"><button className="btn btn-outline" disabled={page === 0} onClick={() => setPage(p => p - 1)}>{ko ? "이전" : "Previous"}</button><span>{page + 1} / {Math.ceil(raw.length / 30)}</span><button className="btn btn-outline" disabled={(page + 1) * 30 >= raw.length} onClick={() => setPage(p => p + 1)}>{ko ? "다음" : "Next"}</button></div>}</details>}
  </section>;
}
