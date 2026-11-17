import {
  buildDefaultPrimarySettings,
  buildDefaultSectionSettings,
} from "@/lib/app-data";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { agentNextPractice, type AgentReport } from "@/lib/agent-report";
import { removeSessionDraft } from "@/lib/session-drafts";
import { uploadSessionVideo, type UploadProgress } from "@/lib/session-upload";
import type { DriftObservation, PersonalCalibration } from "@/lib/calibration";

export type PresentationRecord = {
  id: string;
  title: string;
  date: string;
  duration: string;
  result: string;
  stressAverage: string;
  diagnosis: string;
  nextAction: string;
  sceneLabel: string;
  agentReport?: AgentReport | null;
};

export type DiagnosisRecord = {
  id: string;
  label: string;
  value: string;
  detail: string;
};

export type SessionHistoryRecord = PresentationRecord & {
  durationSeconds: number;
  timeline: number[];
  videoUrl: string | null;
  videoPath: string | null;
  videoError?: string;
  agentReport: AgentReport | null;
};

export type PersistedSettings = {
  primary: Record<string, boolean>;
  sections: Record<string, boolean>;
};

export type SavePracticeSessionInput = {
  id?: string;
  title?: string;
  durationSeconds: number;
  averageStress: number | null;
  result: string;
  diagnosis: string;
  nextAction: string;
  sceneLabel: string;
  timeline: number[];
  video: Blob | null;
  agentReport?: AgentReport | null;
  recordedAt?: string;
};

const LOCAL_HISTORY_KEY = "presense-local-session-history";

function isCoachingAttempt(report: AgentReport | null | undefined) {
  const input = report?.reportInput as { practiceContext?: unknown } | undefined;
  return Boolean(input?.practiceContext);
}

function formatDuration(durationSeconds: number) {
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = durationSeconds % 60;
  return `${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
}

function formatSessionDate(timestamp: string) {
  return new Date(timestamp).toLocaleDateString("sv-SE");
}

function buildDefaultSettings(): PersistedSettings {
  return {
    primary: buildDefaultPrimarySettings(),
    sections: buildDefaultSectionSettings(),
  };
}

export async function ensureUserProfile(userId: string, email: string | undefined, fullName?: string) {
  const supabase = getSupabaseBrowserClient();

  if (!supabase) {
    return;
  }

  const { error } = await supabase.from("profiles").upsert(
    {
      id: userId,
      email: email ?? null,
      full_name: fullName ?? null,
    },
    { onConflict: "id" },
  );

  if (error) {
    throw error;
  }
}

export async function loadUserCalibration(userId: string): Promise<PersonalCalibration | null> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) return null;
  const { data, error } = await supabase.from("user_calibrations")
    .select("baseline_score, sample_count, model_version, calibrated_at, last_prompted_at")
    .eq("user_id", userId).maybeSingle();
  if (error) throw error;
  return data ? {
    score: Number(data.baseline_score), sampleCount: Number(data.sample_count),
    modelVersion: data.model_version, calibratedAt: data.calibrated_at,
    lastPromptedAt: data.last_prompted_at,
  } : null;
}

export async function saveUserCalibration(userId: string, calibration: PersonalCalibration): Promise<void> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) throw new Error("기준선을 저장하려면 로그인해 주세요.");
  const { error } = await supabase.from("user_calibrations").upsert({
    user_id: userId, baseline_score: calibration.score, sample_count: calibration.sampleCount,
    model_version: calibration.modelVersion, calibrated_at: calibration.calibratedAt,
    last_prompted_at: null,
  }, { onConflict: "user_id" });
  if (error) throw error;
}

export async function markCalibrationPrompted(userId: string, at: string): Promise<void> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) return;
  const { error } = await supabase.from("user_calibrations").update({ last_prompted_at: at }).eq("user_id", userId);
  if (error) throw error;
}

export async function loadRecentDriftObservations(): Promise<DriftObservation[]> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) return [];
  const { data, error } = await supabase.from("presentation_records")
    .select("scene_label, session_date, agent_report").order("session_date", { ascending: false }).limit(15);
  if (error) throw error;
  return (data ?? []).map((row) => {
    const report = row.agent_report as AgentReport | null;
    return {
      score: report?.observationReport?.averageStressScore ?? null,
      coverage: report?.observationReport?.coverage ?? 0,
      sceneLabel: row.scene_label ?? "",
      modelVersion: report?.modelVersion ?? "",
      sessionDate: row.session_date,
    };
  });
}

async function updateStoredReport(sessionId: string, patch: (current: AgentReport) => Partial<AgentReport>, columns: Record<string, unknown> = {}) {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) throw new Error("기록을 저장하려면 로그인해 주세요.");
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) throw new Error("다시 로그인한 뒤 저장을 이어갈 수 있어요.");
  for (let attempt = 0; attempt < 5; attempt++) {
    const { data: record, error: readError } = await supabase.from("presentation_records")
      .select("agent_report").eq("id", sessionId).eq("user_id", session.user.id).abortSignal(AbortSignal.timeout(20_000)).single();
    if (readError) throw readError;
    const current = (record.agent_report ?? {}) as AgentReport;
    const revision = current.storageRevision;
    if (revision != null && (!Number.isSafeInteger(revision) || Number(revision) < 0)) throw new Error("저장된 기록의 버전을 확인하지 못했어요.");
    const changes = patch(current);
    if (changes.reportFeedback && (current.reportFeedback?.status === "ready" || current.reportFeedback?.status === "partial")
      && (changes.reportFeedback.status === "failed" || changes.reportFeedback.status === "blocked")) return current;
    const next: AgentReport = { ...current, ...changes, storageRevision: Number(revision ?? 0) + 1 };
    // A newly generated report or stale UI object must not erase coaching.
    if (current.coachingSession) next.coachingSession = current.coachingSession;
    let query = supabase.from("presentation_records").update({ ...columns, agent_report: next })
      .eq("id", sessionId).eq("user_id", session.user.id);
    query = revision == null ? query.is("agent_report->>storageRevision", null) : query.eq("agent_report->>storageRevision", revision);
    const { data: rows, error } = await query.select("id").abortSignal(AbortSignal.timeout(20_000));
    if (error) throw error;
    if (rows?.length) return next;
  }
  throw new Error("다른 화면에서 기록이 변경됐어요. 저장된 내용을 확인하고 다시 시도해 주세요.");
}

export async function saveSessionReflection(sessionId: string, report: AgentReport): Promise<void> {
  await updateStoredReport(sessionId, () => ({ reflection: report.reflection }), { next_action: agentNextPractice(report, false) });
}

export async function loadDashboardData() {
  const supabase = getSupabaseBrowserClient();

  if (!supabase) {
    return {
      presentationRecords: [],
      diagnosisHistory: [],
    };
  }

  const [recordResult, { data: diagnosisRows, error: diagnosisError }] = await Promise.all([
    supabase
      .from("presentation_records")
      .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label, agent_report")
      .order("session_date", { ascending: false }),
    supabase
      .from("diagnosis_history")
      .select("id, label, value, detail, created_at")
      .order("created_at", { ascending: false }),
  ]);

  let { data: recordRows, error: recordError } = recordResult;
  if (recordError && (recordError.code === "42703" || recordError.code === "PGRST204")) {
    const legacy = await supabase.from("presentation_records")
      .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label")
      .order("session_date", { ascending: false });
    recordRows = legacy.data as typeof recordRows;
    recordError = legacy.error;
  }

  if (recordError) {
    throw recordError;
  }

  if (diagnosisError) {
    throw diagnosisError;
  }

  return {
    presentationRecords: (recordRows ?? []).filter((row) => !isCoachingAttempt(row.agent_report && typeof row.agent_report === "object" ? row.agent_report as AgentReport : null)).map((row) => ({
      id: row.id,
      title: row.title,
      date: formatSessionDate(row.session_date),
      duration: formatDuration(row.duration_seconds),
      result: row.result,
      stressAverage: row.stress_average == null ? "—" : Number(row.stress_average).toFixed(2),
      diagnosis: row.diagnosis,
      nextAction: row.next_action ?? "",
      sceneLabel: row.scene_label ?? "",
      agentReport: row.agent_report && typeof row.agent_report === "object" ? row.agent_report as AgentReport : null,
    })) as PresentationRecord[],
    diagnosisHistory: (diagnosisRows ?? []).map((row) => ({
      id: row.id,
      label: row.label,
      value: row.value,
      detail: row.detail,
    })) as DiagnosisRecord[],
  };
}

export async function loadAgentSessions(): Promise<PresentationRecord[]> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) {
    return (await loadSessionHistory()).slice(0, 5);
  }

  const { data, error } = await supabase
    .from("presentation_records")
    .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label, agent_report")
    .order("session_date", { ascending: false })
    .limit(20);
  if (error) throw error;

  return (data ?? []).filter((row) => !isCoachingAttempt(row.agent_report && typeof row.agent_report === "object" ? row.agent_report as AgentReport : null)).map((row) => ({
    id: row.id,
    title: row.title,
    date: formatSessionDate(row.session_date),
    duration: formatDuration(row.duration_seconds),
    result: row.result,
    stressAverage: row.stress_average == null ? "—" : Number(row.stress_average).toFixed(2),
    diagnosis: row.diagnosis,
    nextAction: row.next_action ?? "",
    sceneLabel: row.scene_label ?? "",
  }));
}

export async function loadUserSettings() {
  const supabase = getSupabaseBrowserClient();

  if (!supabase) {
    return buildDefaultSettings();
  }

  const { data, error } = await supabase.from("user_settings").select("primary_settings, section_settings").maybeSingle();

  if (error) {
    throw error;
  }

  if (!data) {
    const defaults = buildDefaultSettings();
    await saveUserSettings(defaults);
    return defaults;
  }

  return {
    primary: {
      ...buildDefaultPrimarySettings(),
      ...(data.primary_settings as Record<string, boolean> | null),
    },
    sections: {
      ...buildDefaultSectionSettings(),
      ...(data.section_settings as Record<string, boolean> | null),
    },
  };
}

export async function loadSessionHistory(): Promise<SessionHistoryRecord[]> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) {
    try {
      return (JSON.parse(window.localStorage.getItem(LOCAL_HISTORY_KEY) ?? "[]") as SessionHistoryRecord[]).filter((row) => !isCoachingAttempt(row.agentReport));
    } catch {
      return [];
    }
  }

  let { data, error } = await supabase
    .from("presentation_records")
    .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label, timeline, video_path, agent_report")
    .order("session_date", { ascending: false });
  // Older projects may not have run the new report migration yet.
  if (error && (error.code === "42703" || error.code === "PGRST204")) {
    const withoutReport = await supabase
      .from("presentation_records")
      .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label, timeline, video_path")
      .order("session_date", { ascending: false });
    data = withoutReport.data as typeof data;
    error = withoutReport.error;
  }
  if (error && (error.code === "42703" || error.code === "PGRST204")) {
    const legacy = await supabase
      .from("presentation_records")
      .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label")
      .order("session_date", { ascending: false });
    data = legacy.data as typeof data;
    error = legacy.error;
  }
  if (error) throw error;

  return Promise.all((data ?? []).filter((row) => !isCoachingAttempt(row.agent_report && typeof row.agent_report === "object" ? row.agent_report as AgentReport : null)).map(async (row) => {
    let videoUrl: string | null = null;
    let videoError: string | undefined;
    if (row.video_path) {
      try {
        const { data: signed, error: signedError } = await supabase.storage.from("session-videos").createSignedUrl(row.video_path, 60 * 60);
        videoUrl = signed?.signedUrl ?? null;
        videoError = signedError?.message;
      } catch {
        videoError = "영상 접근 주소를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.";
      }
    }
    return {
      id: row.id,
      title: row.title,
      date: formatSessionDate(row.session_date),
      duration: formatDuration(row.duration_seconds),
      durationSeconds: Number(row.duration_seconds),
      result: row.result,
      stressAverage: row.stress_average == null ? "—" : Number(row.stress_average).toFixed(2),
      diagnosis: row.diagnosis,
      nextAction: row.next_action ?? "",
      sceneLabel: row.scene_label ?? "",
      timeline: Array.isArray(row.timeline) ? row.timeline.map(Number) : [],
      videoUrl,
      videoPath: row.video_path ?? null,
      videoError,
      agentReport: row.agent_report && typeof row.agent_report === "object" ? row.agent_report as AgentReport : null,
    };
  }));
}

export async function loadSessionVideoUrl(sessionId: string): Promise<string | null> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) {
    const row = (JSON.parse(window.localStorage.getItem(LOCAL_HISTORY_KEY) ?? "[]") as SessionHistoryRecord[]).find(item => item.id === sessionId);
    return row?.videoUrl ?? null;
  }
  const { data, error } = await supabase.from("presentation_records").select("video_path").eq("id", sessionId).maybeSingle();
  if (error) throw error;
  if (!data?.video_path) return null;
  const { data: signed, error: signedError } = await supabase.storage.from("session-videos").createSignedUrl(data.video_path, 60 * 60);
  if (signedError) throw signedError;
  return signed?.signedUrl ?? null;
}

export async function saveUserSettings(settings: PersistedSettings) {
  const supabase = getSupabaseBrowserClient();

  if (!supabase) {
    return;
  }

  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();

  if (userError) {
    throw userError;
  }

  if (!user) {
    throw new Error("No authenticated user found.");
  }

  const { error } = await supabase.from("user_settings").upsert(
    {
      user_id: user.id,
      primary_settings: settings.primary,
      section_settings: settings.sections,
    },
    { onConflict: "user_id" },
  );

  if (error) {
    throw error;
  }
}

export async function savePracticeSession(input: SavePracticeSessionInput) {
  const supabase = getSupabaseBrowserClient();

  if (!supabase) {
    if (input.video) throw new Error("영상 저장에는 서버 연결이 필요합니다.");
    const sessionDate = new Date().toISOString();
    const localRecord: SessionHistoryRecord = {
      id: input.id ?? crypto.randomUUID(),
      title: input.title?.trim() || `${input.sceneLabel} Practice`,
      date: formatSessionDate(sessionDate),
      duration: formatDuration(input.durationSeconds),
      durationSeconds: input.durationSeconds,
      result: input.result,
      stressAverage: input.averageStress?.toFixed(2) ?? "—",
      diagnosis: input.diagnosis,
      nextAction: input.nextAction,
      sceneLabel: input.sceneLabel,
      timeline: input.timeline,
      videoUrl: null,
      videoPath: null,
      agentReport: input.agentReport ?? null,
    };
    const existing = await loadSessionHistory();
    window.localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify([localRecord, ...existing]));
    return;
  }

  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();

  if (userError) {
    throw userError;
  }

  if (!user) {
    throw new Error("로그인이 만료되었습니다. 다시 로그인한 뒤 저장해 주세요.");
  }

  const sessionDate = input.recordedAt ?? new Date().toISOString();
  const recordId = input.id ?? crypto.randomUUID();
  const recordInput = {
    id: recordId, user_id: user.id,
    title: input.title?.trim() || `${input.sceneLabel} Practice`,
    session_date: sessionDate, duration_seconds: input.durationSeconds,
    result: input.result, stress_average: input.averageStress,
    diagnosis: input.diagnosis, next_action: input.nextAction,
    scene_label: input.sceneLabel, timeline: input.timeline, video_path: null,
    ...(input.agentReport ? { agent_report: input.agentReport } : {}),
  };
  // Stable ID makes a retry safe even when the first response was lost.
  const { error: recordError } = await supabase.from("presentation_records")
    .upsert(recordInput, { onConflict: "id", ignoreDuplicates: true })
    .abortSignal(AbortSignal.timeout(20_000));
  if (recordError) throw new Error(`세션 기록을 서버에 저장하지 못했어요: ${recordError.message}`);
  let warning: string | undefined;
  if (input.video) {
    try { await uploadPracticeVideo(recordId, input.video); }
    catch (error) {
      warning = `세션 기록은 저장됐어요. 영상 업로드는 다시 시도해 주세요. ${error instanceof Error ? error.message : ""}`;
    }
  }
  if (input.agentReport?.generationState === "pending") return { warning };

  const diagnosisEntries = [
    {
      user_id: user.id,
      label: "Latest session result",
      value: input.result,
      detail: `${input.sceneLabel} rehearsal completed on ${formatSessionDate(sessionDate)}.`,
    },
    {
      user_id: user.id,
      label: "Average stress",
      value: input.averageStress?.toFixed(2) ?? "—",
      detail: input.diagnosis,
    },
    {
      user_id: user.id,
      label: "Next coaching focus",
      value: input.nextAction,
      detail: "Generated from the most recent practice session.",
    },
  ];

  try {
    const { error: diagnosisError } = await supabase.from("diagnosis_history").insert(diagnosisEntries);
    if (diagnosisError) throw diagnosisError;
  } catch (error) {
    const detail = error && typeof error === "object" && "message" in error ? String(error.message) : "네트워크 오류";
    return { warning: `세션은 저장됐지만 대시보드 요약 갱신에 실패했습니다: ${detail}` };
  }
  return { warning };
}

export async function deletePracticeSession(id: string, videoPath: string | null) {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) {
    const remaining = (await loadSessionHistory()).filter((record) => record.id !== id);
    window.localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(remaining));
    await removeSessionDraft(id).catch(() => undefined);
    return;
  }

  if (videoPath) {
    await supabase.storage.from("session-videos").remove([videoPath]);
  }
  const { error } = await supabase.from("presentation_records").delete().eq("id", id);
  if (error) throw error;
  await removeSessionDraft(id).catch(() => undefined);
}


export async function uploadPracticeVideo(sessionId: string, video: Blob, onProgress?: (value: UploadProgress) => void) {
  const supabase = getSupabaseBrowserClient();
  const { data } = await supabase!.auth.getSession();
  if (!data.session) throw new Error("다시 로그인한 뒤 영상 업로드를 이어갈 수 있어요.");
  const extension = video.type.includes("mp4") ? "mp4" : "webm";
  const path = `${data.session.user.id}/${sessionId}.${extension}`;
  await uploadSessionVideo(path, video, onProgress);
  const { error } = await supabase!.from("presentation_records").update({ video_path: path })
    .eq("id", sessionId).eq("user_id", data.session.user.id)
    .abortSignal(AbortSignal.timeout(20_000));
  if (error) throw new Error(`영상 연결을 저장하지 못했어요: ${error.message}`);
}

export async function saveGeneratedSessionReport(sessionId: string, report: AgentReport) {
  await updateStoredReport(sessionId, current => ({ ...report,
    ...(Object.hasOwn(current, "selfFeedback") ? { selfFeedback: current.selfFeedback } : {}),
    ...(current.reflection?.segmentId === report.reflection?.segmentId && current.reflection?.answer
      ? { reflection: { ...report.reflection!, answer: current.reflection.answer } } : {}),
  }), {
    diagnosis: report.summaryText,
    next_action: agentNextPractice(report, false),
    result: report.generationState === "failed" ? "Report needs retry" : report.generationState === "pending" ? "Report pending" : "AI report complete",
    stress_average: typeof report.analysis.averageStress === "number" ? report.analysis.averageStress : null,
  });
}
export async function saveSessionNote(sessionId: string, note: string) {
  await updateStoredReport(sessionId, () => ({ selfFeedback: note }));
}
