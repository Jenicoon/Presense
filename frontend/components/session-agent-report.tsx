"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { ArrowRight, Gauge, Layers3, Sparkles } from "lucide-react";
import { bilingualLabel, findingText, findingGuidance, signalScore } from "@/lib/report-locale";
import { generateAgentReport } from "@/lib/agent-report";
import { saveGeneratedSessionReport } from "@/lib/supabase/data";
import { savedReportInput } from "@/lib/pending-report";
import { summarizeWindows } from "@/lib/report-windows";
import { StressChart } from "@/components/stress-chart";
import { verifiedPracticePlan } from "@/lib/practice-experiments";
import { ReportPractice } from "@/components/report-practice";
import { AgentEvidence, AgentModelOutputs } from "@/components/agent-observation-report";
import { agentReflectionInterpretation, reportIntentReflection, savedReportAiFeedback, showPriorityAdvice, type AgentReport } from "@/lib/agent-report";
import { completeReportEvidence } from "@/lib/finding-evidence";
import { measurementLabel } from "@/lib/measurement-labels";
import { ReportAiFeedback } from "@/components/report-ai-feedback";
import { practiceMethods, type PracticeMethodId } from "@/lib/practice-experiments";
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
      last.endMs - last.startMs < durationMs / 120
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
  return <StressChart cells={cells} durationMs={duration} language={language} baseline={report.observationReport?.personalBaseline?.score} onSelect={onSeek} />;
}

export function SessionAgentReport({ report, language, onSeek, practiceVideoUrl, pauseReportVideo, practiceHref, showTimeline = true, children, onReportChange }: {
  report: AgentReport;
  language: "ko" | "en";
  onSeek?: (ms: number) => void;
  practiceVideoUrl?: string;
  pauseReportVideo?: () => void;
  practiceHref?: string;
  showTimeline?: boolean;
  children?: ReactNode;
  onReportChange?: (report: AgentReport) => void;
}) {
  const [activePractice, setActivePractice] = useState<string | null>(null);
  const [practiceBusy, setPracticeBusy] = useState(false);
  const [replacement, setReplacement] = useState<AgentReport | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");
  report = replacement?.sessionId === report.sessionId ? replacement : report;
  report = completeReportEvidence(report);
  report = { ...report, reflection: onSeek ? reportIntentReflection(report) : undefined };
  const ko = language === "ko";
  const [page, setPage] = useState(0);
  const [hasSavedCoaching, setHasSavedCoaching] = useState(false);
  const [coachingReadyFor, setCoachingReadyFor] = useState<string | null>(null);
  const [coachingBlockedFor, setCoachingBlockedFor] = useState<string | null>(null);
  if (coachingBlockedFor === report.sessionId) report = { ...report, coachingAvailable: false, coachingDisabledReason: "dataset_privacy" };
  if (coachingReadyFor === report.sessionId && report.dataOrigin !== "stressid" && report.coachingDisabledReason !== "dataset_privacy") {
    report = { ...report, coachingAvailable: true, coachingDisabledReason: undefined };
  }
  useEffect(() => {
    let cancelled = false;
    const refresh = () => void restoreCoach(report.sessionId, language).then(data => {
      if (!cancelled) {
        setHasSavedCoaching(data.messages.length > 0);
        if (data.dataOrigin === "stressid") setCoachingBlockedFor(report.sessionId);
        else setCoachingReadyFor(report.sessionId);
      }
    }).catch(() => undefined);
    if (report.generationState !== "pending" && report.generationState !== "failed" && report.dataOrigin !== "stressid" && report.coachingDisabledReason !== "dataset_privacy") refresh();
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
  const references = (report.referenceFindings ?? []).flatMap(finding => (finding.observations ?? []).map(observation=>({finding,observation})));
  const baseline = report.observationReport?.personalBaseline;
  const baselineScore = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)} / 100` : "—";
  const difference = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}${ko ? "점" : " points"}`;
  const groupedWindows = summarizeWindows(raw, duration);
  const hasVerifiedFeedback = report.priorities.some(f => f.evidenceStatus === "cited_excerpt"
    && (f.recommendation || f.reviewAction || f.practiceSuggestion)
    && f.evidenceIds?.some(id => report.evidence?.some(source => source.id === id)));
  const findingIds = report.priorities.map(finding => finding.id).join(",");
  useEffect(() => {
    try {
      const selected = sessionStorage.getItem(`presense-report-practice:${report.sessionId}`);
      if (selected && report.priorities.some(finding => finding.id === selected)) setActivePractice(selected);
    } catch { /* A stored recording can still be restored when opened manually. */ }
  }, [report.sessionId, findingIds]);
  useEffect(() => {
    if (!activePractice) return;
    try { sessionStorage.setItem(`presense-report-practice:${report.sessionId}`, activePractice); } catch { /* Optional open-card preference. */ }
  }, [report.sessionId, activePractice]);
  const feedbackMissing = report.synthesisStatus === "unavailable" || report.synthesisStatus === "generated" && (!hasVerifiedFeedback
    || report.practiceDefinitionVersion !== "personalized-experiments-v2" || report.language !== language);
  async function retrySavedReport() {
    const input = savedReportInput(report);
    if (!input || retrying) return;
    setRetrying(true);
    setRetryError("");
    try {
      const { segments, ...reportInput } = { ...input, language };
      const ready = { ...await generateAgentReport({ ...reportInput, segments }), generationState: "ready", reportInput, selfFeedback: report.selfFeedback };
      await saveGeneratedSessionReport(report.sessionId, ready);
      setReplacement(ready);
      onReportChange?.(ready);
      if (ready.synthesisStatus === "unavailable") setRetryError(ko ? "개별 AI 피드백을 아직 준비하지 못했어요. 분석 결과는 저장돼 있습니다." : "Individual AI feedback is still unavailable. Your analysis results are saved.");
      window.dispatchEvent(new Event("presense:session-saved"));
    } catch (error) {
      setRetryError(error instanceof Error ? error.message : (ko ? "보고서 생성에 실패했어요." : "Report generation failed."));
    } finally { setRetrying(false); }
  }
  if (report.generationState === "pending" || report.generationState === "failed") return <section className="review-section" aria-label={ko ? "저장된 발표 기록" : "Saved session record"}>
    <h3>{ko ? "발표 기록은 저장됐어요" : "Your session record is saved"}</h3>
    <p>{ko ? "분석 자료를 보관하고 있어요. 보고서 생성은 여기에서 다시 시작할 수 있습니다." : "Your observations are retained. You can start report generation again here."}</p>
    {typeof report.selfFeedback === "string" && report.selfFeedback && <p>{report.selfFeedback}</p>}
    <button type="button" className="btn btn-primary" disabled={retrying || !savedReportInput(report)} onClick={() => void retrySavedReport()}>{retrying ? (ko ? "보고서 생성 중…" : "Preparing report…") : (ko ? "보고서 생성 이어가기" : "Resume report generation")}</button>
    {retryError && <p role="alert" className="error-msg">{retryError}</p>}
  </section>;
  const open = (findingId?: string) => window.dispatchEvent(new CustomEvent("presense:open-agent", {
    detail: { sessionId: report.sessionId, findingId },
  }));
  return <section className="session-agent-report" aria-label={ko ? "세션 분석과 코칭" : "Session analysis and coaching"}>
    <ReportAiFeedback report={report} language={language} summaryOnly onChange={next => { setReplacement(next); onReportChange?.(next); }} />
    {report.dataOrigin === "stressid" && <p className="review-context" role="status">{ko ? "StressID 예시 영상을 기기에서 분석한 결과입니다. 이 자료는 외부 AI 코칭에 전송하지 않습니다." : "This StressID example was analyzed on this device. Its data is not sent to external AI coaching."}</p>}
    {report.dataOrigin === "synthetic" && <p className="review-context" role="status">{ko ? "합성 예시 분석 자료입니다." : "This analysis uses synthetic sample data."}</p>}
    {baseline && <section className="review-section review-baseline" aria-label={ko ? "초기 측정값과 비교" : "Comparison with the initial reference"}>
      <div className="review-section-heading"><div><h3>{ko ? "초기 측정값과 이번 발표 비교" : "Initial reference and this presentation"}</h3><p>{ko ? `10초씩 ${baseline.sampleCount}회 · 측정값 중 가운데 값을 초기값으로 사용합니다.` : `${baseline.sampleCount} separate ten-second measurements · their median is the initial reference.`}</p></div><Gauge size={18} color="var(--accent)" /></div>
      <div className="review-baseline-values"><div><span>{baseline.source === "dataset_example" ? (ko ? "예시 초기값" : "Example reference") : (ko ? "저장된 초기값" : "Saved initial reference")}</span><strong>{baselineScore(baseline.score)}</strong><small>{(baseline.observedMs ?? baseline.sampleCount * 10000) / 1000}{ko ? "초 측정" : "s measured"}</small></div><div><span>{ko ? "이번 발표 평균" : "This presentation's mean"}</span><strong>{baselineScore(a.averageStress)}</strong><small>{ko ? "초기값 대비 " : "From initial: "}{difference(baseline.averageDifference)}</small></div><div><span>{ko ? "가장 높았던 구간" : "Peak interval"}</span><strong>{baselineScore(a.peakStress)}</strong><small>{ko ? "초기값 대비 " : "From initial: "}{difference(baseline.peakDifference)}</small></div></div>
      {baseline.source === "dataset_example" && <details className="review-details">
        <summary>{ko ? "예시 초기값 안내" : "About the example reference"}</summary>
        <p>{ko ? "이 예시 영상의 앞부분에서 측정한 초기값입니다." : "The reference comes from the opening of this example video."}</p>
      </details>}
    </section>}
    {!baseline && report.baselineComparison?.status === "missing" && <p className="review-context" role="status">{ko ? "이 세션에 저장된 초기 측정값이 없어 개인 초기값 비교는 생략했습니다." : "No initial measurement was saved for this session, so a personal-reference comparison is unavailable."}</p>}
    {!baseline && report.baselineComparison?.status === "model_mismatch" && <p className="review-context" role="status">{ko ? "초기 측정과 발표의 분석 조건이 달라 비교하지 않았습니다. 초기값을 다시 측정해 주세요." : "The initial measurement and presentation used different analysis conditions. Remeasure the initial reference to compare them."}</p>}
    <details className="review-details review-score-explainer"><summary>{ko ? "스트레스 신호 점수는 무엇인가요?" : "What does the stress signal score mean?"}</summary><p>{ko ? "음성·영상의 스트레스 관련 패턴을 AI가 0–100으로 표시한 참고 점수입니다." : "A 0–100 reference score for stress-related patterns the AI detects in your voice and video."}</p></details>
    {report.previousCoaching && <p className="review-context">{ko ? "이전 목표" : "Previous goal"} · {bilingualLabel(report.previousCoaching.goalLabel, ko, ko ? "저장된 연습 목표" : "Saved practice goal")}{!report.previousCoaching.comparable && (ko ? " · 분석 조건이 달라 수치 비교를 보류합니다." : " · Analysis conditions differ; numerical comparison is unavailable.")}</p>}
    {showTimeline && <div className="review-timeline-layout">
    <section className="review-section review-timeline">
      <div className="panel-head"><div className="panel-head-left"><h3 className="panel-title">{ko ? "세션 스트레스 신호 타임라인" : "Session Stress Signal Timeline"}</h3><span className="panel-subtitle">{ko ? "발표 후 전체 흐름" : "Post-session overview"}</span></div><Layers3 size={16} color="var(--text-secondary)" /></div>
      <StressChart cells={cells} durationMs={duration} language={language} baseline={report.observationReport?.personalBaseline?.score} onSelect={onSeek} />
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
      <div className="review-timeline-key"><span><i />{ko ? "관측된 스트레스 신호" : "Observed stress signal"}</span><span><i className="gap" />{ko ? "분석 자료 없음" : "No analysis data"}</span>{baseline && <span><i className="baseline" />{ko ? `${(baseline.observedMs ?? baseline.sampleCount * 10000) / 1000}초 초기 측정값` : "Initial measurement reference"}</span>}</div>
    </section>
    <aside className="review-section review-timeline-aside" aria-label={ko ? "발표 분석 요약" : "Presentation analysis summary"}>
      <div className="panel-head"><div className="panel-head-left"><h3 className="panel-title">{ko ? "발표 분석" : "Presentation Analysis"}</h3><span className="panel-subtitle">{ko ? "이번 세션에서 확인할 것" : "What to review"}</span></div><Sparkles size={16} color="var(--text-secondary)" /></div>
      <div className="coach-stack">
        <div className={`coach-card ${first ? "coach-alert" : "coach-ok"}`}><h4>{ko ? "확인할 부분" : "Review focus"}</h4><p>{first ? findingGuidance(first, ko).observation : Number(a.coverage ?? 0) < .5 ? (ko ? "분석 자료가 부족해 주요 문제를 판단하지 않았습니다." : "Insufficient data to judge major issues.") : references.length ? (ko ? "아래 구간별 측정 결과를 참고해 전달 방식을 검토하세요." : "Review the delivery at the reference intervals below.") : (ko ? "우선적으로 살펴볼 변화는 없습니다." : "No change was selected for priority review.")}</p>{first?.observations?.[0] && onSeek && <button type="button" className="review-time-link" onClick={() => onSeek(first.observations![0].startMs)}>{ko ? "근거 영상 보기" : "View supporting video"}<ArrowRight size={13} /></button>}</div>
        <div className="coach-card coach-data"><h4>{ko ? "스트레스 신호가 가장 높았던 구간" : "Peak stress signal"}</h4><p>{typeof a.peakStress === "number" ? signalScore(a.peakStress) : (ko ? "분석 자료 없음" : "No analysis data")}{peak && <><br /><button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(peak.startMs)}>{clock(peak.startMs)}–{clock(peak.endMs)}{onSeek && <ArrowRight size={13} />}</button></>}</p></div>
      </div>
    </aside>
    </div>}
    <AgentModelOutputs report={report} ko={ko} />
    {first && <section className="review-findings"><div className="review-section-heading"><div><h3>{ko ? "주요 검토 항목" : "Priority review items"}</h3><p>{ko ? "주요 변화가 확인된 구간과 권장 연습입니다." : "Selected changes and recommended practice."}</p></div><span className="review-count">{report.priorities.length}</span></div>
    {report.priorities.map((f, index) => {
      const text = findingText(f, ko);
      const view = findingGuidance(f, ko);
      const showAdvice = showPriorityAdvice(report, f.ranges ?? []);
      const savedItem = (report.reportFeedback?.status === "ready" || report.reportFeedback?.status === "partial")
        ? report.reportFeedback.items?.find(item => item.findingId === f.id) : undefined;
      const aiFeedback = showAdvice ? savedItem
        ? { kind: savedItem.practice ? "practice" as const : "review" as const,
            text: `${savedItem.explanation[language]}\n\n${savedItem.review[language]}` }
        : savedReportAiFeedback(report, f, ko) : null;
      const review = showAdvice ? view.question : agentReflectionInterpretation(report, ko);
      const patterns = (f.observations ?? []).filter(o => Object.keys(o.conceptValues).length > 0);
      const savedPractice = savedItem?.practice;
      const practiceTarget = savedPractice && savedItem?.segmentIds.includes(savedPractice.segmentId)
        ? f.observations?.find(row => row.segmentId === savedPractice.segmentId) : undefined;
      const aiPlan = savedPractice && practiceTarget && practiceMethods(f.id).includes(savedPractice.strategyId as PracticeMethodId)
        ? { strategyId: savedPractice.strategyId as PracticeMethodId, startMs: practiceTarget.startMs, endMs: practiceTarget.endMs,
            instructions: { reason: savedPractice.reason[language], goal: savedPractice.goal[language],
              steps: savedPractice.steps.map(step => step[language]), question: savedPractice.question[language] } }
        : report.language === language ? verifiedPracticePlan(report, f) : null;
      const experiment = aiPlan?.instructions;
      const practiceInterval = aiPlan;
      return <article key={f.id} className="review-finding">
        <div className="review-finding-heading"><span className="review-finding-number">{String(index + 1).padStart(2, "0")}</span><h4>{view.title}</h4><span className="review-finding-count">{f.findingKind === "distinct" ? (ko ? "한 구간의 두드러진 변화" : "A distinct change in one interval") : (ko ? `확인할 영상 ${f.observations?.length ?? 0}곳` : `${f.observations?.length ?? 0} intervals to review`)}</span></div>
        <p className="review-finding-summary">{view.observation}</p>
        <div className="review-supporting-times" role="group" aria-label={ko ? "근거가 된 관측 구간" : "Supporting observation intervals"}>{f.observations?.map((o, n) => <button key={o.segmentId} type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(o.startMs)}>{n + 1}. {clock(o.startMs)}–{clock(o.endMs)}</button>)}</div>
        <details className="review-details"><summary>{ko ? "관측 근거와 측정값 보기" : "Observation evidence"}</summary><p>{text.observation}</p><div className="review-observations">{f.observations?.map(o => <div className="review-observation" key={o.segmentId}>
          <button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(o.startMs)}>▶ {clock(o.startMs)}–{clock(o.endMs)}</button>
          <span>{measurementLabel(f.metric ?? "", ko)}<strong>{Number(o.value.toFixed(2))}</strong></span>
          <span>{ko ? "스트레스 신호 점수" : "Stress signal score"}<strong>{signalScore(o.stressScore)}</strong></span>
        </div>)}</div></details>
        <div className="review-finding-action">
          {aiFeedback && <div>
            <strong>{aiFeedback.kind === "practice"
              ? (ko ? "AI 피드백 · 권장 연습" : "AI feedback · Practice")
              : (ko ? "AI 피드백 · 확인 사항" : "AI feedback · What to review")}</strong>
            <p>{aiFeedback.text}</p>
            <AgentEvidence report={report} ids={savedItem?.paperIds ?? f.evidenceIds} ko={ko} />
          </div>}
          {review && !savedItem && aiFeedback?.kind !== "review" && <div>
            <strong>{showAdvice ? (ko ? "확인 사항" : "What to review") : (ko ? "전달 의도 확인 결과" : "Delivery intent response")}</strong>
            <p>{review}</p>
          </div>}
        </div>
        {experiment && activePractice !== f.id && <div className="review-experiment-preview">
          <strong>{ko ? "AI가 선택한 비교 연습" : "Comparison exercise selected by AI"}</strong>
          <p>{experiment.goal}</p>
          <p>{experiment.reason}</p>
          {aiPlan && <button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(aiPlan.startMs)}>{ko ? "연습할 구간" : "Exercise interval"} · {clock(aiPlan.startMs)}–{clock(aiPlan.endMs)}</button>}
          <details className="review-details"><summary>{ko ? "연습 순서" : "Exercise steps"}</summary><ol>{experiment.steps.map(step => <li key={step}>{step}</li>)}</ol></details>
          <p><strong>{ko ? "비교 기준" : "Comparison question"}</strong><br />{experiment.question}</p>
        </div>}
        {aiPlan && experiment && practiceInterval && (practiceVideoUrl
          ? activePractice === f.id ? <ReportPractice key={`${report.sessionId}:${f.id}:${practiceInterval.startMs}:${practiceInterval.endMs}`}
              sessionId={report.sessionId} findingId={f.id} interval={practiceInterval} videoUrl={practiceVideoUrl} ko={ko}
              strategyId={aiPlan.strategyId} instructions={experiment} onBusyChange={setPracticeBusy} pauseReportVideo={pauseReportVideo}
              measurementReference={practiceTarget && f.metric && f.modality ? { modelVersion: report.modelVersion,
                metricDefinitionVersion: report.metricDefinitionVersion as string | undefined,
                conceptDefinitionVersion: report.conceptDefinitionVersion as string | undefined,
                modality: f.modality, metric: f.metric, value: practiceTarget.value } : undefined} />
            : <button type="button" className="btn btn-outline" disabled={practiceBusy} onClick={() => setActivePractice(f.id)}>{ko ? "이 항목 연습하고 비교하기" : "Rehearse and compare this item"}<ArrowRight size={14}/></button>
          : practiceHref ? <Link className="review-time-link" href={practiceHref}>{ko ? "세션 기록에서 연습하기" : "Rehearse from session history"}</Link>
          : <p className="review-practice-note">{ko ? "원본 영상이 있으면 여기에서 재녹화하고 비교할 수 있어요." : "When the original video is available, you can record and compare a new take here."}</p>)}
        {!aiFeedback && <AgentEvidence report={report} ids={f.retrievedEvidenceIds?.slice(0, 2) ?? f.evidenceIds} ko={ko} related />}
        {patterns.length > 0 && <details className="review-details">
          <summary>{ko ? "관련 측정 지표" : "Related measurements"}</summary>
          {patterns.map(o => <p key={o.segmentId}>{clock(o.startMs)}–{clock(o.endMs)} · {Object.entries(o.conceptValues).map(([k, v]) => `${measurementLabel(k, ko)} ${v.toFixed(3)}`).join(" · ")}</p>)}
        </details>}
      </article>;
    })}</section>}
    {references.length > 0 && <section className="review-section review-reference-findings" aria-label={ko ? "구간별 측정 결과" : "Measurements by interval"}>
      <div className="review-section-heading"><div><h3>{ko ? "구간별 측정 결과" : "Measurements by interval"}</h3><p>{ko ? "시점별 측정값과 해당 구간의 발화·표현을 함께 검토하세요." : "Review each measurement alongside speech and expression in the corresponding interval."}</p></div></div>
      <div className="review-reference-list">{references.map(({finding,observation:o},i)=><article className="review-reference-row" key={`${finding.id}-${o.segmentId}-${i}`}>
        <button type="button" className="review-time-link" disabled={!onSeek} onClick={()=>onSeek?.(o.startMs)}>{clock(o.startMs)}–{clock(o.endMs)}</button>
        <span>{measurementLabel(finding.metric ?? finding.id.split(":").at(-1) ?? "",ko)}</span><strong>{Number(o.value.toFixed(2))}{finding.metric?.startsWith("f0_") ? " Hz" : ""}</strong>
      </article>)}</div>
    </section>}
    {raw.length > 0 && <details className="review-details review-raw">
      <summary>{ko ? `시간별 분석 요약 · 30초 단위 ${groupedWindows.length}구간` : `Analysis summary · ${groupedWindows.length} thirty-second intervals`}</summary>
      <div className="observation-table-wrap"><table className="review-raw-table"><thead><tr>
        <th>{ko ? "구간" : "Interval"}</th><th>{ko ? "평균 스트레스 신호" : "Mean stress signal"}</th><th>{ko ? "분석된 시간" : "Observed time"}</th>
      </tr></thead><tbody>{groupedWindows.map(row => <tr key={row.startMs}>
        <td><button className="review-time-link" type="button" disabled={!onSeek || row.score === null} onClick={() => onSeek?.(row.startMs)}>{clock(row.startMs)}–{clock(row.endMs)}</button></td>
        <td>{row.score === null ? (ko ? "분석 자료 없음" : "No analysis data") : signalScore(row.score)}</td>
        <td>{Math.round(row.observedMs / 1000)} / {Math.round((row.endMs-row.startMs)/1000)}{ko ? "초" : "s"}</td>
      </tr>)}</tbody></table></div>
      <details className="review-details review-original-windows"><summary>{ko ? `세부 분석 결과 ${raw.length}개 보기` : `View all ${raw.length} analysis results`}</summary>
        <div className="observation-table-wrap"><table className="review-raw-table"><thead><tr>
          <th>{ko ? "구간" : "Interval"}</th><th>{ko ? "스트레스 신호" : "Stress signal"}</th><th>{ko ? "자료 상태" : "Quality"}</th>
        </tr></thead><tbody>{raw.slice(page * 20, (page + 1) * 20).map(row => <tr key={row.segmentId}>
          <td>{clock(row.startMs)}–{clock(row.endMs)}</td><td>{signalScore(row.stressScore)}</td>
          <td>{row.quality.audioValid && row.quality.faceDetected ? (ko ? "확인됨" : "Valid") : (ko ? "일부 자료 부족" : "Incomplete")}</td>
        </tr>)}</tbody></table></div>
        {raw.length > 20 && <div className="review-pagination">
          <button type="button" className="btn btn-outline" disabled={page === 0} onClick={() => setPage(p => p-1)}>{ko ? "이전" : "Previous"}</button>
          <span>{page+1} / {Math.ceil(raw.length/20)}</span>
          <button type="button" className="btn btn-outline" disabled={(page+1)*20 >= raw.length} onClick={() => setPage(p => p+1)}>{ko ? "다음" : "Next"}</button>
        </div>}
      </details>
    </details>}
    {typeof report.selfFeedback === "string" && report.selfFeedback && <section className="review-section"><h3>{ko ? "나의 발표 회고" : "My presentation reflection"}</h3><p className="saved-self-feedback">{report.selfFeedback}</p></section>}
    {children}
    {report.coachingAvailable !== false && <div className="review-next-step">
      <span className="review-next-icon"><Sparkles size={19} /></span>
      <div>
        <h3>{ko ? "AI 발표 코칭" : "AI presentation coaching"}</h3>
        <p>{ko ? "보고서에 대해 질문하거나 다음 연습을 진행하세요." : "Ask about the report or continue with a practice exercise."}</p>
      </div>
      <div className="review-coaching-actions">
        <button type="button" className="btn btn-primary" onClick={() => open(hasSavedCoaching ? undefined : first?.id)}>
          {hasSavedCoaching ? (ko ? "코칭 이어가기" : "Continue coaching") : (ko ? "코칭 시작" : "Start coaching")}
          <ArrowRight size={15} />
        </button>
        {!report.reportFeedback && feedbackMissing && savedReportInput(report) && <button type="button" className="btn btn-outline" disabled={retrying} onClick={() => void retrySavedReport()}>{retrying ? (ko ? "맞춤 피드백 준비 중…" : "Preparing tailored feedback…") : (ko ? "맞춤 코칭 생성" : "Generate personalized coaching")}</button>}
        {report.priorities.length > 1 && <details className="review-details">
          <summary>{ko ? "검토 항목 선택" : "Choose a review item"}</summary>
          {report.priorities.map(finding => <button key={finding.id} type="button" className="review-time-link" onClick={() => open(finding.id)}>
            {findingGuidance(finding, ko).title}
          </button>)}
        </details>}
        {retryError && <p className="error-msg" role="alert">{retryError}</p>}
      </div>
    </div>}
    {report.coachingAvailable === false && <p className="review-context" role="status">
      {report.coachingDisabledReason === "dataset_privacy"
        ? (ko ? "AI 코칭은 직접 촬영한 발표에서 이용할 수 있습니다." : "AI coaching is available for your own recordings.")
        : (ko ? "보고서는 저장돼 있어요. AI 코칭 기록 연결을 완료하면 대화를 이어갈 수 있습니다." : "Your report is saved. Coaching will be available once its storage connection is configured.")}
    </p>}
  </section>;
}
