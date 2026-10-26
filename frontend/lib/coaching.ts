import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { INFERENCE_URL } from "@/lib/live-signal";
export type CoachAction =
  | "review"
  | "jump_to_video"
  | "explain_finding"
  | "show_measurements"
  | "create_practice"
  | "start_recording"
  | "finish_recording"
  | "compare_attempts"
  | "retry_practice"
  | "choose_next_goal"
  | "compare_previous_session"
  | "finish_coaching"
  | "ask";
export type CoachState = {
  sessionId: string;
  selectedFindingId: string | null;
  activePracticeId: string | null;
  attemptSessionId: string | null;
  stage:
    | "session_review"
    | "finding_selected"
    | "practice_created"
    | "recording"
    | "evaluating"
    | "comparison_ready"
    | "next_goal"
    | "completed";
  nextGoalId: string | null;
  lastAction?: CoachAction | null;
};
export type CoachChoice = {
  id: string;
  label: string;
  action: CoachAction;
  findingId?: string | null;
};
export type Comparison = {
  previousSessionId: string;
  currentSessionId: string;
  outcome: string;
  compatible: boolean;
  scope: "practice" | "previous_session";
  before: {
    value: number | null;
    windowCount: number;
    independentObservations: number;
    coverage: number;
    quality: number;
  };
  after: Comparison["before"];
  modelScoreChange: number | null;
  referenceValue: number | null;
  measurements: {
    modality: string;
    metric: string;
    before: number;
    after: number;
    difference: number;
    beforeCount: number;
    afterCount: number;
    beforeQuality: number;
    afterQuality: number;
  }[];
  formula: string;
};
export type CoachComponent =
  | { type: "action_choices"; choices: CoachChoice[] }
  | {
      type: "video_segment";
      sessionId: string;
      startMs: number;
      endMs: number;
      label: string;
    }
  | { type: "finding"; findingId: string; label: string }
  | {
      type: "practice";
      practiceId: string;
      label: string;
      instruction: string;
      criterion: string;
      durationSeconds: number;
    }
  | { type: "comparison"; comparison: Comparison }
  | { type: "insufficient_data"; label: string };
export type CoachResponse = {
  message: string;
  components: CoachComponent[];
  conversationState: CoachState;
  revision: number;
};
export type CoachMessage = {
  role: "user" | "agent";
  text: string;
  response?: CoachResponse;
};
export type PracticeContext = { sessionId: string; practiceId: string };
export const activeCoachKey = (user: string) => `presense-coach-active:${user}`;
export const practiceKey = (user: string) => `presense-coach-recording:${user}`;
async function api(path: string, body?: unknown) {
  const client = getSupabaseBrowserClient();
  const session = await client?.auth.getSession();
  const token = session?.data.session?.access_token;
  if (!token) throw new Error("로그인이 필요합니다. / Please sign in.");
  const response = await fetch(`${INFERENCE_URL.replace(/\/$/, "")}${path}`, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(45000),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`,
    );
  return data;
}
export async function restoreCoach(id: string): Promise<{
  conversationState: CoachState;
  revision: number;
  messages: CoachMessage[];
}> {
  return api(`/agent/coach/${encodeURIComponent(id)}`);
}
export async function actCoach(input: {
  sessionId: string;
  action: CoachAction;
  language: "ko" | "en";
  message?: string;
  findingId?: string;
  attemptSessionId?: string;
  revision?: number;
  conversationState?: CoachState;
  previousAction?: CoachAction;
}): Promise<CoachResponse> {
  return api("/agent/coach", input);
}
export function jumpToVideo(sessionId: string, startMs: number) {
  const detail = { sessionId, startMs, handled: false };
  window.dispatchEvent(new CustomEvent("presense:seek-video", { detail }));
  if (!detail.handled)
    window.location.assign(
      `/history?session=${encodeURIComponent(sessionId)}&at=${Math.round(startMs)}`,
    );
}
export function clock(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
