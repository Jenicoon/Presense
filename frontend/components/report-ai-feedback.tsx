"use client";
import { useState } from "react";
import { authorizeReportFeedback, retryReportFeedback, feedbackFailureMessage, type AgentReport } from "@/lib/agent-report";
import { saveGeneratedSessionReport } from "@/lib/supabase/data";
import { ReportPractice } from "@/components/report-practice";
import type { PracticeMethodId } from "@/lib/practice-experiments";
import { clock } from "@/lib/coaching";
import { CheckCircle2, Info, Sparkles, Target } from "lucide-react";

function uniqueSentences(value?: string) {
  if (!value) return value;
  const seen = new Set<string>();
  return value.split(/(?<=[.!?。])\s+/).filter(sentence => {
    const key = sentence.replace(/\s+/g, " ").trim().toLocaleLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key); return true;
  }).join(" ");
}

export function ReportAiFeedback({ report, language, onSeek, videoUrl, pauseVideo, onChange, summaryOnly = false }: {
  report: AgentReport; language: "ko" | "en"; onSeek?: (ms: number) => void; videoUrl?: string;
  pauseVideo?: () => void; onChange: (report: AgentReport) => void; summaryOnly?: boolean;
}) {
  const ko = language === "ko";
  const feedback = report.reportFeedback;
  const [busy, setBusy] = useState(false);
  const [practiceBusy, setPracticeBusy] = useState(false);
  const [error, setError] = useState("");
  const [unsaved, setUnsaved] = useState<AgentReport | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const hasFindings = Boolean(feedback?.items?.length);
  async function retry(authorize = false) {
    setBusy(true); setError("");
    let saving = false;
    try {
      const cached = unsaved?.sessionId === report.sessionId ? unsaved : null;
      if (authorize && !cached) await authorizeReportFeedback(report.sessionId);
      const generated = cached ?? await retryReportFeedback(report.sessionId);
      const next: AgentReport = { ...report, ...generated,
        ...(Object.hasOwn(report, "selfFeedback") ? { selfFeedback: report.selfFeedback } : {}),
        reportInput: generated.reportInput ?? report.reportInput,
      };
      setUnsaved(next);
      onChange(next);
      saving = true;
      await saveGeneratedSessionReport(report.sessionId, next);
      setUnsaved(null);
      if (next.reportFeedback?.status !== "ready") setError(next.reportFeedback?.failedStage === "selection"
        ? (ko ? "AI가 검토할 관측 항목을 선택하지 못했어요. 저장된 측정값으로 선택 단계만 다시 시도할 수 있어요." : "AI could not select an observation to review. Retry only the selection stage from the saved measurements.")
        : (ko ? "AI 문안이 측정 근거 검증을 통과하지 못했어요. 발표 기록은 보관되며 피드백 단계만 다시 시도할 수 있어요." : "The AI wording did not pass measurement-grounding validation. The session is retained; retry only the feedback stage."));
    } catch (cause) { setError(feedbackFailureMessage(cause, ko, saving)); }
    finally { setBusy(false); }
  }
  return <section className="review-section report-ai-feedback" aria-label={ko ? "AI 피드백" : "AI feedback"}>
    <div className="report-ai-heading">
      <span className="report-ai-heading-icon"><Sparkles size={18} /></span>
      <div><h3>{ko ? "AI 맞춤 코칭" : "Personalized AI coaching"}</h3><p>{ko ? "이번 발표의 측정 결과를 바탕으로 정리했어요." : "Based on measurements from this presentation."}</p></div>
    </div>
    {(feedback?.status === "ready" || feedback?.status === "partial") ? <>
      <div className="report-ai-summary"><span>{ko ? "이번 발표" : "This presentation"}</span><p className="review-summary-text">{uniqueSentences(feedback.summary?.[language])}</p></div>
      {(Boolean(feedback.strengths?.length) || (!hasFindings && feedback.nextReview?.[language])) && <div className="report-ai-coaching-grid">
        {Boolean(feedback.strengths?.length) && <div className="report-ai-coaching-card carry">
          <div className="report-ai-card-title"><CheckCircle2 size={18} /><strong>{ko ? "이어갈 점" : "Carry forward"}</strong></div>
          {feedback.strengths?.map((strength, index) => <p className="review-summary-text" key={`${index}:${strength[language]}`}>{strength[language]}</p>)}
        </div>}
        {!hasFindings && feedback.nextReview?.[language] && <div className="report-ai-coaching-card experiment">
          <div className="report-ai-card-title"><Target size={18} /><strong>{ko ? "다음 발표 실험" : "Next-presentation experiment"}</strong></div>
          <p>{feedback.nextReview[language]}</p>
        </div>}
      </div>}
      {!summaryOnly && feedback.items?.map(item => {
        const finding = report.priorities.find(row => row.id === item.findingId);
        if (!finding) return null;
        const observations = finding.observations?.filter(row => item.segmentIds.includes(row.segmentId)) ?? [];
        const plan = item.practice;
        const target = observations.find(row => row.segmentId === plan?.segmentId);
        const papers = report.evidence?.filter(row => item.paperIds.includes(row.id)) ?? [];
        const instructions = plan ? { reason: plan.reason[language], goal: plan.goal[language], steps: plan.steps.map(step => step[language]), question: plan.question[language] } : null;
        return <article className="review-finding" key={item.findingId}>
          <p className="review-finding-summary">{item.observation?.[language]}</p>
          <p className="review-summary-text">{item.explanation[language]}</p>
          <div className="review-supporting-times">{observations.map(row => <button key={row.segmentId} type="button" className="review-time-link" disabled={!onSeek || practiceBusy} onClick={() => onSeek?.(row.startMs)}>
            ▶ {clock(row.startMs)}–{clock(row.endMs)}
          </button>)}</div>
          <p>{item.review[language]}</p>
          {plan && instructions && target && <>
            {active === item.findingId && videoUrl ? <ReportPractice key={`${report.sessionId}:${item.findingId}`}
              sessionId={report.sessionId} findingId={item.findingId} interval={target} videoUrl={videoUrl} ko={ko}
              strategyId={plan.strategyId as PracticeMethodId} instructions={instructions} pauseReportVideo={pauseVideo} onBusyChange={setPracticeBusy}
              measurementReference={target && finding.metric && finding.modality ? { modelVersion: report.modelVersion,
                metricDefinitionVersion: report.metricDefinitionVersion as string | undefined, conceptDefinitionVersion: report.conceptDefinitionVersion as string | undefined,
                modality: finding.modality, metric: finding.metric, value: target.value } : undefined} />
              : <div className="review-experiment-preview"><strong>{instructions.goal}</strong><p>{instructions.reason}</p>
                <details className="review-details"><summary>{ko ? "맞춤 연습 순서와 비교 기준" : "Tailored exercise and comparison"}</summary>
                  <ol>{instructions.steps.map(step => <li key={step}>{step}</li>)}</ol><p>{instructions.question}</p>
                </details>
                {videoUrl && <button className="btn btn-outline" type="button" disabled={practiceBusy} onClick={() => setActive(item.findingId)}>{ko ? "이 보고서에서 재녹화·비교" : "Record and compare in this report"}</button>}
              </div>}
          </>}
          {papers.length > 0 && <details className="review-details"><summary>{ko ? "참고 논문" : "Research references"}</summary>
            {papers.map(paper => <p key={paper.id}><a href={paper.articleUrl ?? (paper.doi ? `https://doi.org/${paper.doi}` : undefined)} target="_blank" rel="noreferrer">{paper.title ?? paper.source}</a><br />{ko ? paper.findingKo : paper.scope}</p>)}
          </details>}
        </article>;
      })}
      {hasFindings && feedback.nextReview?.[language] && <div className="report-ai-coaching-card review">
        <div className="report-ai-card-title"><Target size={18} /><strong>{ko ? "영상에서 확인할 점" : "What to check in the recording"}</strong></div>
        <p>{feedback.nextReview[language]}</p>
      </div>}
      {feedback.limitations?.[language] && !/(?:판단|판정)할 수 없|cannot (?:determine|judge|infer)/i.test(feedback.limitations[language]) && <details className="review-details report-ai-limitations"><summary><Info size={14} />{ko ? "분석 범위" : "Analysis scope"}</summary><p>{feedback.limitations[language]}</p></details>}
      {feedback.status === "partial" && <div role="status"><p>{ko ? "일부 항목의 AI 검토는 완료하지 못했어요. 완료된 피드백과 원본은 유지됩니다." : "Some AI reviews could not finish. Completed feedback and the original are retained."}</p><button className="btn btn-outline" type="button" disabled={busy} onClick={() => void retry()}>{ko ? "미완료 항목만 재시도" : "Retry unfinished items"}</button></div>}
    </> : <>
      <p role="status">{(feedback?.status === "blocked" || !feedback)
        ? (ko ? "이 세션은 외부 AI 분석이 허용되지 않았습니다. 측정 기록은 저장되어 있습니다." : "External AI analysis is not enabled for this session. Measurements are saved.")
        : feedback?.failedStage === "selection"
        ? (ko ? "검토 항목 선택을 완료하지 못했어요. 문제가 없는 발표라는 뜻은 아닙니다." : "Review selection could not finish. This does not mean the presentation had no issues.")
        : (ko ? "맞춤 피드백 생성을 완료하지 못했어요. 발표 기록은 저장되어 있습니다." : "Tailored feedback could not finish. Your session record is saved.")}</p>
      {(feedback?.status === "blocked" || !feedback) && report.dataOrigin !== "stressid" && <button className="btn btn-outline" type="button" disabled={busy} onClick={() => void retry(true)}>
        {ko ? "직접 촬영한 테스트 세션입니다 · 측정값 전송 동의 후 피드백 생성" : "This is my own test recording · Allow measurements and generate feedback"}</button>}
      {feedback && feedback.status !== "blocked" && <button className="btn btn-outline" type="button" disabled={busy} onClick={() => void retry()}>{busy ? (ko ? "피드백 생성 중…" : "Generating feedback…") : (ko ? "실패한 AI 단계 재시도" : "Retry the failed AI stage")}</button>}
    </>}
    {busy && <p role="status">{ko ? "AI 피드백을 준비하고 있어요…" : "Preparing AI feedback…"}</p>}
    {error && <p role="alert" className="error-msg">{error}</p>}
    {unsaved?.sessionId === report.sessionId && <button type="button" className="btn btn-outline" disabled={busy} onClick={() => void retry()}>{ko ? "피드백 저장 재시도" : "Retry saving feedback"}</button>}
  </section>;
}
