"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, Maximize2, Minimize2, RefreshCw, Send, X } from "lucide-react";
import { actCoach, restoreCoach, activeCoachKey, practiceKey, type CoachAction, type CoachState, type CoachMessage } from "@/lib/coaching";
import { CoachComponents } from "@/components/coach-components";
import { useLang } from "@/lib/i18n";
import { loadAgentSessions, type PresentationRecord } from "@/lib/supabase/data";

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
  const [open, setOpen] = useState(false);
  const [preferencesLoaded,setPreferencesLoaded]=useState(false);
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
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
    setMessages([]); setCoachState(null); setRevision(undefined);
    const active = window.localStorage.getItem(activeCoachKey(userId));
    activeSessionRef.current = active;
    if(active) { setFocusSessionId(active); void restoreCoach(active).then(data=>{
      if(activeSessionRef.current!==active) return;
      setMessages(data.messages); setCoachState(data.conversationState); setRevision(data.revision);
    }).catch(()=>setError(lang === "ko" ? "저장된 코칭을 불러오지 못했습니다. 세션 보고서에서 다시 열어 주세요." : "Could not restore coaching. Reopen it from the session report.")); }
  }, [userId]);

  useEffect(() => {
    if(!preferencesLoaded) return;
    window.sessionStorage.setItem(OPEN_KEY, open ? "1" : "0");
    if (open) {
      void refreshSessions();
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open, refreshSessions,preferencesLoaded]);

  useEffect(() => {
    function handleOpen(event: Event) {
      const detail = (event as CustomEvent<OpenAgentDetail>).detail;
      setCurrentReport(detail?.report ?? null);
      setOpen(true);
      if(detail?.sessionId && userId) {
        const id=detail.sessionId; activeSessionRef.current=id; setFocusSessionId(id);
        setMessages([]); setCoachState(null); setRevision(undefined);
        window.localStorage.setItem(activeCoachKey(userId),id);
        setBusy(true);setError("");
        void restoreCoach(id).then(async data=>{
          if(activeSessionRef.current!==id) return;
          setMessages(data.messages);setCoachState(data.conversationState);setRevision(data.revision);
          if(detail.attemptSessionId || detail.findingId || data.messages.length===0) {
            const response=await actCoach({sessionId:id, action:detail.attemptSessionId?"finish_recording":detail.findingId?"explain_finding":"review", language:lang, findingId:detail.findingId, attemptSessionId:detail.attemptSessionId, revision:data.revision});
            if(activeSessionRef.current!==id) return;
            setCoachState(response.conversationState);setRevision(response.revision);
            setMessages(previous=>[...previous,{role:"agent",text:response.message,response}]);
            if(detail.attemptSessionId) window.localStorage.removeItem(practiceKey(userId));
          }
        }).catch(failure=>setError(failure instanceof Error?failure.message:t("agent.requestFailed"))).finally(()=>setBusy(false));
      }
    }
    function handleSaved() { void refreshSessions(); }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("presense:open-agent", handleOpen);
    window.addEventListener("presense:session-saved", handleSaved);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("presense:open-agent", handleOpen);
      window.removeEventListener("presense:session-saved", handleSaved);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [refreshSessions, userId, lang, t]);

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [messages, open, busy]);

  async function sendMessage(action: CoachAction = "ask", findingId?: string) {
    const question = input.trim();
    const id=activeSessionRef.current || focusSessionId;
    if(busy || (action === "ask" && !question)) return;
    if(!id) { setError(lang === "ko" ? "먼저 분석 보고서가 있는 세션을 선택해 주세요." : "Select a session with an analysis report first."); return; }
    setInput(""); setError(""); setBusy(true);
    if(question) setMessages(previous=>[...previous,{role:"user",text:question}]);
    try {
      const response=await actCoach({sessionId:id,action,language:lang,message:question,findingId,revision,conversationState:coachState ?? undefined,previousAction});
      if(activeSessionRef.current!==id) return;
      setCoachState(response.conversationState);setRevision(response.revision);setPreviousAction(action);
      setMessages(previous=>[...previous,{role:"agent",text:response.message,response}]);
      if((action==="start_recording" || action==="retry_practice") && userId && response.conversationState.activePracticeId) {
        window.localStorage.setItem(practiceKey(userId),JSON.stringify({sessionId:id,practiceId:response.conversationState.activePracticeId}));
        if(window.location.pathname!=="/practice") window.location.assign(`/practice?coaching=${encodeURIComponent(id)}`);
        else window.dispatchEvent(new CustomEvent("presense:coach-start",{detail:response.conversationState}));
      }
      if(action==="finish_recording") window.dispatchEvent(new CustomEvent("presense:coach-stop",{detail:{sessionId:id}}));
    } catch(failure) { setError(failure instanceof Error?failure.message:t("agent.requestFailed"));
      // Recover authoritative state after another tab won a revision race.
      try { const restored=await restoreCoach(id);setCoachState(restored.conversationState);setRevision(restored.revision); } catch {}
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

          <div className="agent-panel-messages" role="log" aria-live="polite" ref={messagesRef}>
            {messages.length === 0 && <div className="agent-panel-welcome"><BrainCircuit size={25} /><p>{t("agent.welcome")}</p></div>}
            {coachState && <p className="coach-stage">{lang === "ko" ? "진행 단계" : "Coaching stage"}: {({session_review:lang==="ko"?"보고서 검토":"Review", finding_selected:lang==="ko"?"발견 확인":"Finding", practice_created:lang==="ko"?"연습 준비":"Practice ready", recording:lang==="ko"?"녹화":"Recording", evaluating:lang==="ko"?"분석 중":"Evaluating", comparison_ready:lang==="ko"?"비교 완료":"Comparison ready", next_goal:lang==="ko"?"다음 목표":"Next goal", completed:lang==="ko"?"완료":"Completed"})[coachState.stage]}</p>}
            {messages.map((message, index) => <div key={index} className={`agent-panel-message ${message.role}`}>{message.text}{message.response && <CoachComponents components={message.response.components} ko={lang === "ko"} busy={busy || index !== messages.length-1} onAction={(action,id)=>void sendMessage(action,id)} />}</div>)}
            {busy && <div className="agent-panel-message agent pending">{t("agent.thinking")}</div>}
          </div>

          <div className="agent-panel-compose">
            {error && <p className="agent-panel-error" role="alert">{error}</p>}
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
