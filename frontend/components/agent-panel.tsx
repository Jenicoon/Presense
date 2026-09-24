"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BrainCircuit, Maximize2, Minimize2, RefreshCw, Send, X } from "lucide-react";
import { INFERENCE_URL } from "@/lib/live-signal";
import { useLang } from "@/lib/i18n";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
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

type AgentMessage = { role: "user" | "agent"; text: string };
type OpenAgentDetail = { report?: CurrentAgentReport };

const OPEN_KEY = "presense-agent-open";
const EXPANDED_KEY = "presense-agent-expanded";
const CHAT_KEY_PREFIX = "presense-agent-chat:";

export function AgentPanel({ userId }: { userId: string | null }) {
  const { lang, t } = useLang();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [loadedUserId, setLoadedUserId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<PresentationRecord[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sessionsError, setSessionsError] = useState(false);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(null);
  const [currentReport, setCurrentReport] = useState<CurrentAgentReport | null>(null);
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
  }, []);

  useEffect(() => { window.sessionStorage.setItem(EXPANDED_KEY, expanded ? "1" : "0"); }, [expanded]);

  useEffect(() => {
    if (!userId) {
      setMessages([]);
      setLoadedUserId(null);
      return;
    }
    try {
      const stored = JSON.parse(window.sessionStorage.getItem(`${CHAT_KEY_PREFIX}${userId}`) ?? "[]");
      setMessages(Array.isArray(stored) ? stored.filter((item) =>
        (item.role === "user" || item.role === "agent") && typeof item.text === "string"
      ).slice(-20) : []);
    } catch {
      setMessages([]);
    }
    setLoadedUserId(userId);
  }, [userId]);

  useEffect(() => {
    if (userId && loadedUserId === userId) {
      window.sessionStorage.setItem(`${CHAT_KEY_PREFIX}${userId}`, JSON.stringify(messages.slice(-20)));
    }
  }, [loadedUserId, messages, userId]);

  useEffect(() => {
    window.sessionStorage.setItem(OPEN_KEY, open ? "1" : "0");
    if (open) {
      void refreshSessions();
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open, refreshSessions]);

  useEffect(() => {
    function handleOpen(event: Event) {
      const detail = (event as CustomEvent<OpenAgentDetail>).detail;
      setCurrentReport(detail?.report ?? null);
      setOpen(true);
    }
    function handleSaved() { setCurrentReport(null); void refreshSessions(); }
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
  }, [refreshSessions]);

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [messages, open, busy]);

  async function sendMessage() {
    const question = input.trim();
    if (!question || busy || sessionsLoading) return;
    setInput("");
    setError("");
    setBusy(true);
    setMessages((previous) => [...previous, { role: "user", text: question }]);

    try {
      const supabase = getSupabaseBrowserClient();
      if (!supabase || !userId) throw new Error(t("agent.signIn"));
      const { data: { session }, error: sessionError } = await supabase.auth.getSession();
      if (sessionError || !session?.access_token) throw new Error(t("agent.signIn"));

      const response = await fetch(`${INFERENCE_URL.replace(/\/$/, "")}/agent/chat`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: question.slice(0, 1200),
          language: lang,
          report: currentReport,
          sessions: sessions.slice(0, 5).map((record) => ({
            id: record.id,
            title: record.title.slice(0, 160),
            date: record.date,
            duration: record.duration,
            result: record.result.slice(0, 240),
            stressAverage: Number(record.stressAverage),
            diagnosis: record.diagnosis.slice(0, 700),
            nextAction: record.nextAction.slice(0, 500),
            sceneLabel: record.sceneLabel.slice(0, 120),
          })),
          focusSessionId,
          history: messages.slice(-8).map((message) => ({
            role: message.role === "agent" ? "assistant" : "user",
            content: message.text.slice(0, 1000),
          })),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : t("agent.requestFailed"));
      if (typeof data.reply !== "string" || !data.reply.trim()) throw new Error(t("agent.emptyReply"));
      setMessages((previous) => [...previous, { role: "agent", text: data.reply.trim() }]);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t("agent.requestFailed"));
    } finally {
      setBusy(false);
    }
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
                <button type="button" className={!focusSessionId ? "selected" : ""} onClick={() => setFocusSessionId(null)}>{t("agent.allRecent")}</button>
                {sessions.map((session) => (
                  <button key={session.id} type="button" className={focusSessionId === session.id ? "selected" : ""} onClick={() => setFocusSessionId(session.id)} title={`${session.title} · ${session.date}`}>
                    <span>{session.title}</span><small>{session.date}</small>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="agent-panel-messages" role="log" aria-live="polite" ref={messagesRef}>
            {messages.length === 0 && <div className="agent-panel-welcome"><BrainCircuit size={25} /><p>{t("agent.welcome")}</p></div>}
            {messages.map((message, index) => <div key={index} className={`agent-panel-message ${message.role}`}>{message.text}</div>)}
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
