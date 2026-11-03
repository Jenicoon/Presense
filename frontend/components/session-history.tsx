"use client";

import { SessionAgentReport } from "@/components/session-agent-report";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { BrainCircuit, CalendarDays, Film, FolderClock, Gauge, Languages, LoaderCircle, Play, Sparkles, Trash2, X } from "lucide-react";
import { useLang } from "@/lib/i18n";
import { StressChart } from "@/components/stress-chart";
import { AgentObservationReport } from "@/components/agent-observation-report";
import { durationText, sceneText, signalScore } from "@/lib/report-locale";
import { reportDisplaySummary } from "@/lib/agent-report";
import { deletePracticeSession, loadSessionHistory, saveSessionReflection, type SessionHistoryRecord } from "@/lib/supabase/data";
import type { AgentReport } from "@/lib/agent-report";

function severity(score: number) { return !Number.isFinite(score) ? "sev-unknown" : score >= 0.7 ? "sev-high" : score >= 0.5 ? "sev-medium" : "sev-low"; }

function localizeRecordText(value: string, t: (key: string, fallback?: string) => string) {
  const fixed: Record<string, string> = {
    "Mostly stable delivery": "diag.stableDelivery",
    "Practice slower transitions between your main explanation blocks and leave a short pause after each key term.": "diag.nextAction",
  };
  if (fixed[value]) return t(fixed[value]);
  const phaseKey = (phase: string) => `diag.phase.${phase.toLowerCase()}`;
  const pressure = value.match(/^Noticeable (Open|Build|Core|Close)-section pressure$/i);
  if (pressure) return t("diag.noticeablePressure").replace("{phase}", t(phaseKey(pressure[1])));
  const peak = value.match(/^Peak pressure reached (\d+(?:\.\d+)?)% around the (Open|Build|Core|Close) phase\. Deck: (.+)\.$/);
  if (peak) return t("diag.peakPressure").replace("{value}", peak[1]).replace("{phase}", t(phaseKey(peak[2]))).replace("{deck}", peak[3] === "No deck used" ? t("diag.noDeck") : peak[3]);
  return value;
}

function Timeline({ values, onSelect }: { values: number[]; onSelect?: (index: number) => void }) {
  if (!values.length) return <span className="history-no-timeline">No timeline saved</span>;
  return <div className="history-timeline" aria-label="Model signal timeline">
    {values.map((value, index) => onSelect ? <button key={index} type="button" className={value >= 70 ? "high" : value >= 50 ? "mid" : "low"} style={{ flex: Math.max(value, 20) }} title={`Model score ${value}/100`} onClick={() => onSelect(index)} /> : <span key={index} className={value >= 70 ? "high" : value >= 50 ? "mid" : "low"} style={{ flex: Math.max(value, 20) }} title={`Model score ${value}/100`} />)}
  </div>;
}

function ReviewModal({ record, ko, t, onClose, onReportUpdate }: { record: SessionHistoryRecord; ko: boolean; t: (key: string, fallback?: string) => string; onClose: () => void; onReportUpdate: (report: AgentReport) => Promise<void> }) {
  const { toggle } = useLang();
  const [coachOpen, setCoachOpen] = useState(false);
  useEffect(() => {
    setCoachOpen(window.sessionStorage.getItem("presense-agent-open") === "1");
    function visibility(event: Event) { setCoachOpen(!!(event as CustomEvent<{open: boolean}>).detail.open); }
    window.addEventListener("presense:agent-visibility", visibility);
    return () => window.removeEventListener("presense:agent-visibility", visibility);
  }, []);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [answerError, setAnswerError] = useState("");
  const [answerBusy, setAnswerBusy] = useState(false);
  const durationProbeRef = useRef(false);
  const requestedSeekRef=useRef<number | null>(null);
  useEffect(()=>{const at=Number(new URLSearchParams(window.location.search).get("at"));requestedSeekRef.current=Number.isFinite(at)&&at>=0?at/1000:null;},[]);
  const probeTimeoutRef = useRef<number | null>(null);
  useEffect(() => () => {
    if (probeTimeoutRef.current !== null) window.clearTimeout(probeTimeoutRef.current);
  }, []);
  useEffect(()=>{
    function seek(event: Event) { const d=(event as CustomEvent<{sessionId:string;startMs:number;handled?:boolean}>).detail; if(d.sessionId===record.id && videoRef.current) {d.handled=true;videoRef.current.currentTime=d.startMs/1000;void videoRef.current.play().catch(()=>undefined);} }
    window.addEventListener("presense:seek-video",seek);return ()=>window.removeEventListener("presense:seek-video",seek);
  },[record.id]);
  const peak = record.agentReport?.observationReport?.peakSegment
    ? Math.round(record.agentReport.observationReport.peakSegment.stressScore * 100)
    : record.timeline.length ? Math.max(...record.timeline) : 0;
  const [playbackError, setPlaybackError] = useState(false);
  const phases = ko ? ["도입", "전개", "핵심", "마무리"] : ["Open", "Build", "Core", "Close"];
  const averages = phases.map((_, p) => {
    const values = record.timeline.slice(Math.floor(p * record.timeline.length / 4), Math.floor((p + 1) * record.timeline.length / 4));
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  });
  const peakBin = record.agentReport?.observationReport?.peakSegment && record.durationSeconds
    ? Math.min(record.timeline.length - 1, Math.floor(record.agentReport.observationReport.peakSegment.startMs / (record.durationSeconds * 1000) * record.timeline.length))
    : record.timeline.indexOf(peak);
  const strongest = record.timeline.length ? averages.indexOf(Math.max(...averages.map((v) => v ?? -1))) : -1;
  function restoreVideoStart(video: HTMLVideoElement) {
    if (!durationProbeRef.current || !Number.isFinite(video.duration)) return;
    durationProbeRef.current = false;
    if (probeTimeoutRef.current !== null) window.clearTimeout(probeTimeoutRef.current);
    probeTimeoutRef.current = null;
    video.currentTime = requestedSeekRef.current ?? 0;
  }
  function checkVideoDuration(video: HTMLVideoElement) {
    if(requestedSeekRef.current!==null && Number.isFinite(video.duration)) {video.currentTime=Math.min(requestedSeekRef.current,video.duration);void video.play().catch(()=>undefined);}
    if (!record.videoPath?.toLowerCase().endsWith(".webm")) return;
    const expected = record.durationSeconds;
    if (Number.isFinite(video.duration) && (!expected || Math.abs(video.duration - expected) <= Math.max(2, expected * 0.1))) return;
    durationProbeRef.current = true;
    video.pause();
    video.currentTime = 1e10;
    probeTimeoutRef.current = window.setTimeout(() => {
      durationProbeRef.current = false;
      video.currentTime = 0;
      probeTimeoutRef.current = null;
    }, 4000);
  }
  function seekToBin(bin: number) {
    const video = videoRef.current;
    if (!video) return;
    const expected = record.durationSeconds;
    const duration = expected && (!Number.isFinite(video.duration)
      || Math.abs(video.duration - expected) > Math.max(2, expected * 0.1))
      ? expected : video.duration;
    if (!duration || !Number.isFinite(duration)) return;
    video.currentTime = ((bin + 0.5) / Math.max(record.timeline.length, 1)) * duration;
    void video.play().catch(() => undefined);
  }
  async function answerReflection(answer: "intentional" | "unintentional" | "unsure") {
    if (!record.agentReport?.reflection || answerBusy) return;
    setAnswerError("");
    setAnswerBusy(true);
    const next = { ...record.agentReport, reflection: { ...record.agentReport.reflection, answer } };
    try { await onReportUpdate(next); }
    catch (error) { setAnswerError(error instanceof Error ? error.message : "응답을 저장하지 못했습니다."); }
    finally { setAnswerBusy(false); }
  }
  return <div className="modal-backdrop" onClick={onClose} role="presentation"><section className="card history-review-modal" role="dialog" aria-modal={coachOpen ? undefined : true} aria-labelledby="history-review-title" onClick={(event) => event.stopPropagation()}>
    <div className="review-modal-controls"><button type="button" onClick={toggle} aria-label={ko ? "영어로 보기" : "View in Korean"}><Languages size={15} /><span>{ko ? "EN" : "한국어"}</span></button><button type="button" onClick={onClose} aria-label={ko ? "세션 리뷰 닫기" : "Close session review"}><X size={18} /></button></div>
    <div className="diagnosis-modal-eyebrow">{ko ? "세션 리뷰" : "Session review"}</div>
    <h2 id="history-review-title" className="diagnosis-modal-title">{record.title}</h2>
    <div className="history-review-meta"><span><CalendarDays size={13} /> {record.date} · {durationText(record.duration, ko)}</span><span className={`severity-pill ${severity(Number(record.stressAverage))}`}>{ko ? "평균 스트레스 신호" : "Mean stress signal score"} {signalScore(record.stressAverage)}</span></div>
    <div className={`review-overview${record.agentReport ? "" : " video-only"}`}>
    <div className="history-review-video">
      {record.videoUrl ? <><video ref={videoRef} controls playsInline preload="metadata" src={record.videoUrl} onLoadedMetadata={(event) => checkVideoDuration(event.currentTarget)} onDurationChange={(event) => restoreVideoStart(event.currentTarget)} onError={() => setPlaybackError(true)} />{playbackError && <p role="alert" className="error-msg">{ko ? "영상 재생에 실패했습니다. 페이지를 새로고침해 재시도해 주세요." : "Playback failed. Refresh the page to retry."}</p>}</> : <div className="history-video-empty"><Film size={24} /><strong>{record.videoPath ? (ko ? "영상 불러오기 실패" : "Could not load video") : (ko ? "저장된 영상이 없습니다" : "No saved video")}</strong><span>{record.videoPath ? (ko ? "영상 경로는 저장되어 있지만 접근할 수 없습니다. 저장소 권한을 확인해 주세요." : "The video path exists but cannot be accessed. Check storage permissions.") : (ko ? "이 기록에는 영상 경로가 없습니다. 당시 녹화 또는 업로드가 완료되지 않았을 수 있습니다." : "This record has no video path. Recording or upload may not have completed.")}</span></div>}
    </div>
    {record.agentReport && <section className="review-overview-summary"><span className="review-eyebrow">{ko ? "이번 발표 요약" : "Session summary"}</span><h3>{ko ? "발표 분석 보고서" : "Presentation analysis report"}</h3><p>{reportDisplaySummary(record.agentReport, ko)}</p><span className="review-summary-note">{ko ? "분석 점수는 영상·음성과 함께 살펴보세요." : "Read analysis scores alongside the recording."}</span></section>}
    </div>
    {record.agentReport && <>
      <SessionAgentReport report={record.agentReport} language={ko ? "ko" : "en"} onSeek={record.videoUrl ? ms=>{if(videoRef.current){videoRef.current.currentTime=ms/1000;void videoRef.current.play().catch(()=>undefined);}} : undefined} />
      <details className="review-details review-supplement"><summary>{ko ? "발표 흐름과 상세 측정값" : "Session patterns and detailed measurements"}</summary><AgentObservationReport report={record.agentReport} ko={ko} onAnswer={answerBusy ? undefined : answer => void answerReflection(answer)} />{answerError && <p role="alert" className="error-msg">{answerError}</p>}</details>
    </>}
    {!record.agentReport && <div className="history-review-section"><div className="history-review-section-head"><div><strong>{ko ? "모델 신호 타임라인" : "Model signal timeline"}</strong><span>{record.videoUrl ? (ko ? "구간을 누르면 영상의 해당 시점으로 이동합니다" : "Select a segment to jump to that moment in the video") : (ko ? "영상 없이도 저장된 스트레스 신호 점수를 확인할 수 있습니다" : "Saved model scores are available without video")}</span></div><strong className="history-peak">{peak ? `${peak}% ${ko ? "최고" : "peak"}` : "–"}</strong></div><Timeline values={record.timeline} onSelect={record.videoUrl ? seekToBin : undefined} /><div className="video-timeline-legend"><span><i className="low" />{ko ? "낮은 스트레스 신호 점수" : "Lower model score"}</span><span><i className="mid" />{ko ? "중간 스트레스 신호 점수" : "Middle model score"}</span><span><i className="high" />{ko ? "높은 스트레스 신호 점수" : "Higher model score"}</span></div></div>}
    {!record.agentReport && <div className="history-review-coaching"><div className="coach-card coach-alert"><h3>{ko ? "세션 결과" : "Session result"}</h3><p>{localizeRecordText(record.result, t)}</p></div><div className="coach-card coach-data"><h3>{ko ? "발표 분석" : "Presentation analysis"}</h3><p>{localizeRecordText(record.diagnosis, t)}</p></div><div className="coach-card coach-ok"><h3>{ko ? "다음 연습 포인트" : "Next practice focus"}</h3><p>{localizeRecordText(record.nextAction, t)}</p></div></div>}
    {!record.agentReport && <section className="history-review-section" style={{ marginTop: 16 }}>
      <h3>{ko ? "표시 구간별 스트레스 신호 점수" : "Model scores by display interval"}</h3>
      <p>{ko ? "전체 연습 시간을 네 구간으로 나눈 요약입니다. 그래프 범위는 0~100%입니다." : "The session is divided into four equal phases. Chart range: 0–100%."}</p>
      <StressChart series={record.timeline} />
      <div className="report-grid" style={{ marginTop: 16 }}>
        <div className="report-card"><div className="rc-label">{ko ? "전체 평균" : "Average"}</div><div className="rc-value">{Math.round(Number(record.stressAverage) * 100)}%</div></div>
        <div className="report-card"><div className="rc-label">{ko ? "최고 스트레스 신호" : "Peak stress signal score"}</div><div className="rc-value">{record.timeline.length ? `${peak}%` : "—"}</div><div className="rc-desc">{peakBin >= 0 ? `${phases[Math.min(3, Math.floor(peakBin * 4 / record.timeline.length))]} · ${peakBin + 1}/${record.timeline.length}` : "—"}</div></div>
        <div className="report-card"><div className="rc-label">{ko ? "평균 스트레스 신호가 가장 높은 구간" : "Highest average phase"}</div><div className="rc-value">{strongest >= 0 ? phases[strongest] : "—"}</div></div>
        <div className="report-card"><div className="rc-label">{ko ? "연습 환경 / 시간" : "Scene / duration"}</div><div className="rc-value" style={{ fontSize: 16 }}>{record.sceneLabel} · {durationText(record.duration, ko)}</div></div>
      </div>
      <div className="history-review-coaching">{phases.map((phase, i) => <div key={phase} className="coach-card coach-data"><h3>{phase}</h3><p>{averages[i] === null ? (ko ? "저장된 데이터 없음" : "No saved data") : `${ko ? "구간 평균 스트레스 신호" : "Mean stress signal score"}: ${averages[i]!.toFixed(1)}%`}</p></div>)}</div>
    </section>}
  </section></div>;
}

export function SessionHistory() {
  const { lang, t } = useLang(); const ko = lang === "ko";
  const [records, setRecords] = useState<SessionHistoryRecord[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState(""); const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    setSelectedId(new URLSearchParams(window.location.search).get("session") ?? "");
    void loadSessionHistory().then(setRecords).catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load history.")).finally(() => setLoading(false));
  }, []);
  const selected = records.find((record) => record.id === selectedId);
  const average = useMemo(() => (()=>{const values=records.map(r=>Number(r.stressAverage)).filter(Number.isFinite);return values.length?values.reduce((a,b)=>a+b,0)/values.length:NaN;})(), [records]);
  const videoCount = records.filter((record) => record.videoUrl).length;
  const latestPeak = records[0]?.agentReport?.observationReport?.peakSegment
    ? Math.round(records[0].agentReport.observationReport.peakSegment.stressScore * 100)
    : records[0]?.timeline.length ? Math.max(...records[0].timeline) : 0;
  function closeReview() {
    setSelectedId("");
    const url = new URL(window.location.href);
    if (url.searchParams.has("session")) {
      url.searchParams.delete("session");
      window.history.replaceState(window.history.state, "", url);
    }
  }
  async function handleDelete(record: SessionHistoryRecord) {
    const message = ko
      ? `“${record.title}” 기록을 삭제할까요? 저장된 영상도 함께 삭제되며 되돌릴 수 없습니다.`
      : `Delete “${record.title}”? Its saved video will also be deleted and this cannot be undone.`;
    if (!window.confirm(message)) return;
    try {
      await deletePracticeSession(record.id, record.videoPath);
      setRecords((items) => items.filter((item) => item.id !== record.id));
      if (selectedId === record.id) setSelectedId("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to delete session.");
    }
  }
  return <main className="page-content">
    <div className="page-top"><div><h1 className="page-title">{ko ? "기록" : "History"}</h1><p className="page-subtitle">{ko ? "저장한 세션 결과와 발표 분석을 한곳에서 확인하세요." : "Review your saved session results and presentation analysis in one place."}</p></div><div className="page-actions"><Link href="/practice" className="btn btn-primary"><Play size={14} />{ko ? "새 연습 시작" : "Start practice"}</Link></div></div>
    <div className="kpi-row"><div className="kpi-card"><div className="kpi-top"><div className="kpi-icon"><FolderClock size={16} /></div></div><div className="kpi-value">{records.length}</div><div className="kpi-label">{ko ? "저장된 세션" : "Saved sessions"}</div><div className="kpi-sub">{ko ? "기록에서 다시 볼 수 있습니다" : "Available in your history"}</div></div><div className="kpi-card"><div className="kpi-top"><div className="kpi-icon" style={{ background: "var(--accent-ok-light)", color: "var(--accent-ok)" }}><Gauge size={16} /></div></div><div className="kpi-value">{signalScore(average)}</div><div className="kpi-label">{ko ? "평균 스트레스 신호" : "Mean stress signal score"}</div><div className="kpi-sub">{ko ? "전체 기록 기준" : "Across all saved sessions"}</div></div><div className="kpi-card"><div className="kpi-top"><div className="kpi-icon" style={{ background: "rgba(245,158,11,0.1)", color: "var(--accent-warn)" }}><Film size={16} /></div></div><div className="kpi-value">{videoCount}</div><div className="kpi-label">{ko ? "저장된 영상" : "Saved videos"}</div><div className="kpi-sub">{ko ? "선택한 경우에만 보관" : "Kept only when selected"}</div></div><div className="kpi-card"><div className="kpi-top"><div className="kpi-icon" style={{ background: "rgba(139,92,246,0.1)", color: "#7c3aed" }}><Sparkles size={16} /></div></div><div className="kpi-value">{latestPeak ? `${latestPeak} / 100` : "–"}</div><div className="kpi-label">{ko ? "최근 최고 스트레스 신호" : "Latest peak model score"}</div><div className="kpi-sub">{ko ? "최근 세션 기준" : "For the latest session"}</div></div></div>
    {loading ? <p className="state-loading"><LoaderCircle size={16} /> {ko ? "기록을 불러오는 중..." : "Loading history..."}</p> : null}{error ? <p className="error-msg">{error}</p> : null}{!loading && !error && records.length === 0 ? <div className="state-empty history-platform-empty"><BrainCircuit size={24} /><strong>{ko ? "아직 저장된 세션이 없습니다" : "No saved sessions yet"}</strong><span>{ko ? "연습 종료 후 저장하면 이곳에 표시됩니다." : "Save a session after practice and it will appear here."}</span></div> : null}
    {records.length > 0 ? <div className="card history-table-card"><div className="history-panel-header"><div className="panel-head-left"><span className="panel-title">{ko ? "세션 기록" : "Session records"}</span><span className="panel-subtitle">{ko ? "저장된 분석 결과" : "Saved analysis results"}</span></div><CalendarDays size={16} color="var(--text-secondary)" /></div><div className="table-wrap"><table className="data-table"><thead><tr><th>{ko ? "날짜" : "Date"}</th><th>{ko ? "세션" : "Session"}</th><th>{ko ? "시간" : "Duration"}</th><th>{ko ? "평균 스트레스 신호" : "Mean stress signal score"}</th><th>{ko ? "영상" : "Video"}</th><th>{ko ? "보기" : "Review"}</th></tr></thead><tbody>{records.map((record) => <tr key={record.id}><td className="td-mono">{record.date}</td><td style={{ fontWeight: 500 }}>{record.title}<small className="history-scene">{sceneText(record.sceneLabel, ko)}</small></td><td className="td-mono">{durationText(record.duration, ko)}</td><td><span className={`severity-pill ${severity(Number(record.stressAverage))}`}>{signalScore(record.stressAverage)}</span></td><td>{record.videoUrl ? <Film size={15} color="var(--accent)" /> : <span className="history-muted">–</span>}</td><td><div className="history-table-actions"><button type="button" className="table-action" onClick={() => setSelectedId(record.id)}>{ko ? "상세 보기" : "View details"}</button><button type="button" className="history-delete" onClick={() => void handleDelete(record)} aria-label={ko ? "기록 삭제" : "Delete record"}><Trash2 size={14} /></button></div></td></tr>)}</tbody></table></div></div> : null}
    {!loading && selectedId && !selected && <p role="status">{ko?"선택한 세션의 저장된 영상 기록이 없습니다. 영상을 저장한 세션에서 다시 확인해 주세요.":"No saved video record exists for the selected session. Open a session with a saved recording."}</p>}
    {selected ? <ReviewModal record={selected} ko={ko} t={t} onClose={closeReview} onReportUpdate={async (next) => {
      await saveSessionReflection(selected.id, next);
      setRecords((items) => items.map((item) => item.id === selected.id ? { ...item, agentReport: next } : item));
    }} /> : null}
  </main>;
}
