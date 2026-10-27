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
  | "ask"
  | "confirm_intent"
  | "guide_review"
  | "explain_score"
  | "assess_delivery_achieved"
  | "assess_delivery_partial"
  | "assess_delivery_retry";
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
  reviewFeedback?: "intentional" | "needs_practice" | "unsure" | null;
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
  evaluationMode?: "delivery_review" | "measurement_comparison";
  assessmentSource?: "presenter" | "none";
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
async function api(path: string, body?: unknown, language: "ko" | "en" = "ko") {
  const ko = language === "ko";
  const client = getSupabaseBrowserClient();
  const session = await client?.auth.getSession();
  const token = session?.data.session?.access_token;
  if (!token) throw new Error(ko ? "로그인이 필요합니다." : "Please sign in.");
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
  if (!response.ok) {
    const errors: Record<number, [string, string]> = {
      401: ["다시 로그인해 주세요.", "Please sign in again."],
      404: ["저장된 분석 자료가 없습니다. 먼저 보고서를 생성해 주세요.", "No saved analysis data is available. Generate a report first."],
      409: ["다른 화면에서 코칭이 변경되었습니다. 다시 열어 주세요.", "Coaching changed in another window. Reopen it to continue."],
      422: ["현재 단계에서 실행할 수 없는 요청입니다. 안내된 행동을 선택해 주세요.", "This action is unavailable at the current stage. Choose one of the suggested actions."],
      503: ["코칭을 저장하지 못했습니다. 연결을 확인하고 다시 시도해 주세요.", "Coaching could not be saved. Check the connection and retry."],
    };
    throw new Error(errors[response.status]?.[ko ? 0 : 1] ?? (ko ? "코칭에 연결하지 못했습니다. 다시 시도해 주세요." : "Could not reach the coach. Please try again."));
  }
  return data;
}
export async function restoreCoach(id: string, language: "ko" | "en" = "ko"): Promise<{
  conversationState: CoachState;
  revision: number;
  messages: CoachMessage[];
}> {
  return api(`/agent/coach/${encodeURIComponent(id)}?language=${language}`, undefined, language);
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
  const response = await api("/agent/coach", input, input.language);
  window.dispatchEvent(new CustomEvent("presense:coach-changed", {detail: {sessionId: input.sessionId}}));
  return response;
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
