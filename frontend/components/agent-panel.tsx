"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, Maximize2, Minimize2, RefreshCw, Send, X } from "lucide-react";
import { actCoach, restoreCoach, activeCoachKey, practiceKey, type CoachAction, type CoachState, type CoachMessage, type CoachActionContext } from "@/lib/coaching";
import { CoachComponents } from "@/components/coach-components";
import { useLang } from "@/lib/i18n";
import { loadAgentSessions, loadSessionVideoUrl, type PresentationRecord } from "@/lib/supabase/data";
import { formatCoachMeasurementNumbers } from "@/lib/coach-format";

export type CurrentAgentReport = {
  startBaseline: number;
  averageStress: number;
  peakValue: number;
  peakPhase: string;
  mostStressfulPhase: string;
  confidence: number;
  noticeable: boolean;
};

type AgentMessage = CoachMessage;
type OpenAgentDetail = { report?: CurrentAgentReport; sessionId?: string; findingId?: string; attemptSessionId?: string };

const OPEN_KEY = "presense-agent-open";
const EXPANDED_KEY = "presense-agent-expanded";

export function AgentPanel({ userId }: { userId: string | null }) {
  const { lang, t } = useLang();
  const languageRef = useRef(lang);
  languageRef.current = lang;
  const [open, setOpen] = useState(false);
  const [preferencesLoaded,setPreferencesLoaded]=useState(false);
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [historyStart, setHistoryStart] = useState(0);
  const [historyExpanded, setHistoryExpanded] = useState(false);
  const [resumed, setResumed] = useState(false);
  const [sessions, setSessions] = useState<PresentationRecord[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState(false);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(null);
  const [currentReport, setCurrentReport] = useState<CurrentAgentReport | null>(null);
  const [coachState, setCoachState] = useState<CoachState | null>(null);
  const [revision, setRevision] = useState<number | undefined>();
  const [previousAction, setPreviousAction] = useState<CoachAction | undefined>();
  const activeSessionRef = useRef<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const lastOpenRef = useRef<OpenAgentDetail | null>(null);
  const failedActionRef = useRef<{action: CoachAction; findingId?: string; context?: CoachActionContext} | null>(null);
  const videoRequest = useRef(0);
  const [videoReview, setVideoReview] = useState<{ url: string; label: string; startMs: number; endMs: number } | null>(null);
  const [videoLoading, setVideoLoading] = useState(false);
  const [videoError, setVideoError] = useState("");

  async function showVideo(sessionId: string, startMs: number, endMs: number, label: string) {
    const request = ++videoRequest.current;
    setVideoLoading(true); setVideoError(""); setVideoReview(null);
    try {
      const url = await loadSessionVideoUrl(sessionId);
      if (request !== videoRequest.current) return;
      if (!url) throw new Error(lang === "ko" ? "이 촬영의 저장된 영상이 없습니다." : "No saved video is available for this take.");
      setVideoReview({ url, label, startMs, endMs });
    } catch (failure) {
      if (request === videoRequest.current) setVideoError(failure instanceof Error ? failure.message : (lang === "ko" ? "영상을 불러오지 못했습니다." : "Could not load the video."));
    } finally { if (request === videoRequest.current) setVideoLoading(false); }
  }

  const refreshSessions = useCallback(async () => {
    if (!userId) {
      setSessions([]);
      return;
    }
    setSessionsLoading(true);
    setSessionsError(false);
    try {
      setSessions(await loadAgentSessions());
    } catch {
      setSessionsError(true);
    } finally {
      setSessionsLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    setOpen(window.sessionStorage.getItem(OPEN_KEY) === "1");
    setExpanded(window.sessionStorage.getItem(EXPANDED_KEY) === "1");
    setPreferencesLoaded(true);
  }, []);

  useEffect(() => { if(preferencesLoaded) window.sessionStorage.setItem(EXPANDED_KEY, expanded ? "1" : "0"); }, [expanded,preferencesLoaded]);

  useEffect(() => {
    if (!userId) {
      setMessages([]); activeSessionRef.current=null;setCoachState(null);setRevision(undefined);
      return;
    }
    setMessages([]);setError(""); setCoachState(null); setRevision(undefined);
    const active = window.localStorage.getItem(activeCoachKey(userId));
    activeSessionRef.current = active;
    let cancelled = false;
    if(active) { setFocusSessionId(active); void restoreCoach(active, lang).then(data=>{
      if(cancelled || activeSessionRef.current!==active) return;
      setMessages(data.messages); setHistoryStart(Math.max(0, data.messages.length - 1));setResumed(data.messages.length > 0);
      setCoachState(data.conversationState); setRevision(data.revision);
    }).catch(failure=>setError(failure instanceof Error ? failure.message : (lang === "ko" ? "저장된 코칭을 불러오지 못했습니다. 세션 보고서에서 다시 열어 주세요." : "Could not restore coaching. Reopen it from the session report."))); }
    return () => { cancelled = true; };
  }, [userId, lang]);

  useEffect(() => {
    if(!preferencesLoaded) return;
    window.sessionStorage.setItem(OPEN_KEY, open ? "1" : "0");
    window.dispatchEvent(new CustomEvent("presense:agent-visibility", {detail: {open}}));
    if (open) {
      void refreshSessions();
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open, refreshSessions,preferencesLoaded]);

  useEffect(() => {
    function handleOpen(event: Event) {
      const detail = (event as CustomEvent<OpenAgentDetail>).detail;
      lastOpenRef.current = detail; failedActionRef.current = null;
      setCurrentReport(detail?.report ?? null);
      videoRequest.current += 1; setVideoReview(null); setVideoLoading(false); setVideoError("");
      setOpen(true);
      if(detail?.sessionId && userId) {
        const id=detail.sessionId; activeSessionRef.current=id; setFocusSessionId(id);
        setMessages([]);setHistoryStart(0);setHistoryExpanded(false);setResumed(false); setCoachState(null); setRevision(undefined);
        window.localStorage.setItem(activeCoachKey(userId),id);
        setBusy(true);setError("");
        void restoreCoach(id, lang).then(async data=>{
          if(activeSessionRef.current!==id || languageRef.current!==lang) return;
          setMessages(data.messages);setHistoryStart(Math.max(0, data.messages.length - 1));setResumed(data.messages.length > 0);setCoachState(data.conversationState);setRevision(data.revision);
          if(detail.attemptSessionId || (detail.findingId && detail.findingId !== data.conversationState.selectedFindingId) || data.messages.length===0) {
            const response=await actCoach({sessionId:id, action:detail.attemptSessionId?"finish_recording":detail.findingId?"explain_finding":"review", language:lang, findingId:detail.findingId, attemptSessionId:detail.attemptSessionId, revision:data.revision});
            if(activeSessionRef.current!==id || languageRef.current!==lang) return;
            setCoachState(response.conversationState);setRevision(response.revision);
            setMessages(previous=>[...previous,{role:"agent",text:response.message,response}]);
            if(detail.attemptSessionId) {
              window.localStorage.removeItem(practiceKey(userId));
              window.history.replaceState({}, "", `/history?session=${encodeURIComponent(id)}`);
            }
          }
        }).catch(failure=>setError(failure instanceof Error?failure.message:t("agent.requestFailed"))).finally(()=>setBusy(false));
      }
    }
    function handleSaved() { void refreshSessions(); }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    const closePanel = () => setOpen(false);
    window.addEventListener("presense:close-agent", closePanel);
    window.addEventListener("presense:open-agent", handleOpen);
    window.addEventListener("presense:session-saved", handleSaved);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("presense:close-agent", closePanel);
      window.removeEventListener("presense:open-agent", handleOpen);
      window.removeEventListener("presense:session-saved", handleSaved);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [refreshSessions, userId, lang, t]);

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [messages, open, busy]);

  async function sendMessage(action: CoachAction = "ask", findingId?: string, actionContext?: CoachActionContext) {
    const question = input.trim();
    const id=activeSessionRef.current || focusSessionId;
    if(busy || (action === "ask" && !question)) return;
    if(!id) { setError(lang === "ko" ? "먼저 분석 보고서가 있는 세션을 선택해 주세요." : "Select a session with an analysis report first."); return; }
    setInput(""); setError(""); setBusy(true);
    failedActionRef.current = {action, findingId, context: actionContext};
    if(question) setMessages(previous=>[...previous,{role:"user",text:question}]);
    try {
      const response=await actCoach({sessionId:id,action,language:lang,message:question,findingId,revision,conversationState:coachState ?? undefined,previousAction,...actionContext});
      if(activeSessionRef.current!==id) return;
      setCoachState(response.conversationState);setRevision(response.revision);setPreviousAction(action);
      if(languageRef.current === lang) setMessages(previous=>[...previous,{role:"agent",text:response.message,response}]);
      else {
        const restored = await restoreCoach(id, languageRef.current);
        if(activeSessionRef.current!==id) return;
        setMessages(restored.messages);setCoachState(restored.conversationState);setRevision(restored.revision);
      }
      if((action==="start_recording" || action==="retry_practice") && userId && response.conversationState.activePracticeId) {
        window.localStorage.setItem(practiceKey(userId),JSON.stringify({sessionId:id,practiceId:response.conversationState.activePracticeId}));
        if(window.location.pathname!=="/practice") window.location.assign(`/practice?coaching=${encodeURIComponent(id)}`);
        else window.dispatchEvent(new CustomEvent("presense:coach-start",{detail:response.conversationState}));
      }
      if(action==="finish_recording") window.dispatchEvent(new CustomEvent("presense:coach-stop",{detail:{sessionId:id}}));
      failedActionRef.current = null;
    } catch(failure) {
      if (activeSessionRef.current !== id) return;
      setError(failure instanceof Error?failure.message:t("agent.requestFailed"));
      if (question) setInput(current => current || question);
      // Recover authoritative state after another tab won a revision race.
      try {
        const restored=await restoreCoach(id, languageRef.current);
        if (activeSessionRef.current !== id) return;
        setCoachState(restored.conversationState); setRevision(restored.revision);
        setMessages(restored.messages);
        if (revision !== undefined && restored.revision > revision) {
          setError(""); setInput(current => current === question ? "" : current); setResumed(true); setHistoryStart(Math.max(0, restored.messages.length - 1));
        }
      } catch {}
    } finally { setBusy(false); }
  }

  function selectSession(id: string) {
    window.dispatchEvent(new CustomEvent("presense:open-agent",{detail:{sessionId:id}}));
  }

  return (
    <>
      <button type="button" className="agent-mobile-trigger" onClick={() => setOpen(true)} aria-label={t("agent.open")}>
        <BrainCircuit size={21} />
      </button>
      {open && (
        <section className={`agent-panel${expanded ? " expanded" : ""}`} role="dialog" aria-label={t("agent.title")}>
          <div className="agent-panel-header">
            <div className="agent-panel-heading">
              <span className="agent-panel-icon"><BrainCircuit size={20} /></span>
              <div><strong>{t("agent.title")}</strong><span>{t("agent.subtitle")}</span></div>
            </div>
            <div className="agent-panel-controls">
              <button type="button" onClick={() => setExpanded((value) => !value)} aria-label={expanded ? t("agent.shrink") : t("agent.expand")} title={expanded ? t("agent.shrink") : t("agent.expand")}>
                {expanded ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
              </button>
              <button type="button" onClick={() => setOpen(false)} aria-label={t("agent.close")} title={t("agent.close")}><X size={18} /></button>
            </div>
          </div>

          <div className="agent-session-context">
            <div className="agent-session-heading">
              <strong>{t("agent.contextTitle")}</strong>
              <button type="button" onClick={() => void refreshSessions()} disabled={sessionsLoading} aria-label={t("agent.refresh")} title={t("agent.refresh")}><RefreshCw size={15} /></button>
            </div>
            {currentReport && <p className="agent-current-session">{t("agent.currentSession")}</p>}
            {sessionsLoading && <p className="agent-context-note">{t("agent.loadingSessions")}</p>}
            {sessionsError && <p className="agent-context-note error">{t("agent.sessionsError")}</p>}
            {!sessionsLoading && !sessionsError && sessions.length === 0 && <p className="agent-context-note">{t("agent.noSessions")}</p>}
            {sessions.length > 0 && (
              <div className="agent-session-list">
                <button type="button" className={!focusSessionId ? "selected" : ""} onClick={() => { const latest=sessions[0]; if(latest) selectSession(latest.id); }}>{t("agent.allRecent")}</button>
                {sessions.map((session) => (
                  <button key={session.id} type="button" className={focusSessionId === session.id ? "selected" : ""} onClick={() => selectSession(session.id)} title={`${session.title} · ${session.date}`}>
                    <span>{session.title}</span><small>{session.date}</small>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="agent-coaching-context"><strong>{lang === "ko" ? "현재 발표" : "Current presentation"}</strong><span>{sessions.find(session => session.id === focusSessionId)?.title ?? (lang === "ko" ? "선택한 보고서" : "Selected report")}</span></div>
          {resumed && <div className="agent-resume-notice"><strong>{lang === "ko" ? "저장된 코칭을 이어서 보고 있어요" : "Continuing your saved coaching"}</strong><p>{lang === "ko" ? "이 세션에서 진행했던 마지막 단계와 연습을 불러왔습니다." : "Restored the last step and practice from this presentation."}</p>{historyStart > 0 && <button type="button" onClick={() => setHistoryExpanded(value => !value)}>{historyExpanded ? (lang === "ko" ? "현재 단계만 보기" : "Show current step") : lang === "ko" ? "이전 대화 보기" : "View earlier conversation"}</button>}</div>}
          <div className="agent-panel-messages" role="log" aria-live="polite" ref={messagesRef}>
            {messages.length === 0 && <div className="agent-panel-welcome"><BrainCircuit size={25} /><p>{t("agent.welcome")}</p></div>}
            {coachState && <p className="coach-stage">{lang === "ko" ? "진행 단계" : "Coaching stage"}: {({session_review:lang==="ko"?"보고서 검토":"Review", finding_selected:lang==="ko"?"발견 확인":"Finding", practice_created:lang==="ko"?"연습 준비":"Practice ready", recording:lang==="ko"?"녹화":"Recording", evaluating:lang==="ko"?"분석 중":"Evaluating", comparison_ready:lang==="ko"?"비교 완료":"Comparison ready", next_goal:lang==="ko"?"다음 목표":"Next goal", completed:lang==="ko"?"완료":"Completed"})[coachState.stage]}</p>}
            {messages.map((message, index) => (historyExpanded || index >= historyStart) ? <div key={index} className={`agent-panel-message ${message.role}`}>{message.response && <span className="coach-response-source">{message.response.generation?.source === "ai" ? (lang === "ko" ? "AI가 작성한 코칭" : "AI-generated coaching") : (lang === "ko" ? "기본 안내" : "System guidance")}{message.response.generation?.dataOrigin === "synthetic" && <span> · {lang === "ko" ? "합성 예시 분석 기반" : "Synthetic sample analysis"}</span>}{message.response.generation?.dataOrigin === "stressid" && <span> · {lang === "ko" ? "StressID 실제 분석 기반" : "Real StressID analysis"}</span>}</span>}{message.supersededQuestion ? <details className="review-details"><summary>{lang === "ko" ? "이미 답변한 이전 확인 질문" : "Earlier question · already answered"}</summary><p className="agent-message-text">{formatCoachMeasurementNumbers(message.text)}</p></details> : <p className="agent-message-text">{formatCoachMeasurementNumbers(message.text)}</p>}{message.response && <CoachComponents onVideo={(...args) => void showVideo(...args)} components={message.response.components} ko={lang === "ko"} busy={busy || index !== messages.length-1} onAction={(action,id,context)=>void sendMessage(action,id,context)} />}</div> : null)}
            {busy && <div className="agent-panel-message agent pending">{t("agent.thinking")}</div>}
          </div>

          <div className="agent-panel-compose">
            {videoLoading && <p role="status">{lang === "ko" ? "영상 불러오는 중…" : "Loading video…"}</p>}
            {videoError && <p role="alert">{videoError}</p>}
            {videoReview && <div className="agent-video-review">
              <div><strong>{videoReview.label}</strong><button type="button" onClick={() => setVideoReview(null)} aria-label={lang === "ko" ? "영상 닫기" : "Close video"}><X size={16} /></button></div>
              <video key={`${videoReview.url}:${videoReview.startMs}:${videoReview.endMs}`} src={videoReview.url} controls autoPlay playsInline onLoadedMetadata={event => { event.currentTarget.currentTime = videoReview.startMs / 1000; }} onTimeUpdate={event => { if (event.currentTarget.currentTime >= videoReview.endMs / 1000) event.currentTarget.pause(); }} />
            </div>}
            {error && <div className="agent-panel-error" role="alert"><p>{error}</p>
          <button type="button" className="btn btn-outline" disabled={busy} onClick={() => {
            const failed = failedActionRef.current;
            if (failed) void sendMessage(failed.action, failed.findingId, failed.context);
            else window.dispatchEvent(new CustomEvent("presense:open-agent", {detail: lastOpenRef.current ?? {sessionId: focusSessionId}}));
          }}>{lang === "ko" ? "이 요청 다시 보내기" : "Retry this request"}</button>
          {(activeSessionRef.current || focusSessionId) && <a href={`/history?session=${encodeURIComponent(activeSessionRef.current || focusSessionId || "")}`}>{lang === "ko" ? "저장된 보고서 보기" : "View saved report"}</a>}
        </div>}
            <div className="agent-panel-input-row">
              <textarea ref={inputRef} value={input} maxLength={1200} rows={2} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
              }} placeholder={t("agent.placeholder")} disabled={busy || sessionsLoading} />
              <button type="button" onClick={() => void sendMessage()} disabled={busy || sessionsLoading || !input.trim()} aria-label={t("agent.send")}><Send size={18} /></button>
            </div>
            <small>{t("agent.privacy")}</small>
          </div>
        </section>
      )}
    </>
  );
}
