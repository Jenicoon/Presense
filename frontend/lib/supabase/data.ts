import {
  buildDefaultPrimarySettings,
  buildDefaultSectionSettings,
} from "@/lib/app-data";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { agentNextPractice, type AgentReport } from "@/lib/agent-report";
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

type SavePracticeSessionInput = {
  id?: string;
  title?: string;
  durationSeconds: number;
  averageStress: number;
  result: string;
  diagnosis: string;
  nextAction: string;
  sceneLabel: string;
  timeline: number[];
  video: Blob | null;
  agentReport?: AgentReport | null;
};

const LOCAL_HISTORY_KEY = "presense-local-session-history";

function formatDuration(durationSeconds: number) {
  const minutes = Math.floor(durationSeconds / 60);
  const seconds = durationSeconds % 60;
  return `${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
}

function formatSessionDate(timestamp: string) {
  return new Date(timestamp).toISOString().slice(0, 10);
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

export async function saveSessionReflection(sessionId: string, report: AgentReport): Promise<void> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) throw new Error("보고서 응답을 저장하려면 로그인해 주세요.");
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) throw authError ?? new Error("로그인 세션을 확인할 수 없습니다.");
  const { error } = await supabase.from("presentation_records")
    .update({ agent_report: report, next_action: agentNextPractice(report, false) }).eq("id", sessionId).eq("user_id", user.id);
  if (error) throw error;
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
    presentationRecords: (recordRows ?? []).map((row) => ({
      id: row.id,
      title: row.title,
      date: formatSessionDate(row.session_date),
      duration: formatDuration(row.duration_seconds),
      result: row.result,
      stressAverage: Number(row.stress_average).toFixed(2),
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
    .select("id, title, session_date, duration_seconds, result, stress_average, diagnosis, next_action, scene_label")
    .order("session_date", { ascending: false })
    .limit(5);
  if (error) throw error;

  return (data ?? []).map((row) => ({
    id: row.id,
    title: row.title,
    date: formatSessionDate(row.session_date),
    duration: formatDuration(row.duration_seconds),
    result: row.result,
    stressAverage: Number(row.stress_average).toFixed(2),
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
      return JSON.parse(window.localStorage.getItem(LOCAL_HISTORY_KEY) ?? "[]") as SessionHistoryRecord[];
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

  return Promise.all((data ?? []).map(async (row) => {
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
      stressAverage: Number(row.stress_average).toFixed(2),
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
      id: crypto.randomUUID(),
      title: input.title?.trim() || `${input.sceneLabel} Practice`,
      date: formatSessionDate(sessionDate),
      duration: formatDuration(input.durationSeconds),
      durationSeconds: input.durationSeconds,
      result: input.result,
      stressAverage: input.averageStress.toFixed(2),
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

  const sessionDate = new Date().toISOString();
  const title = input.title?.trim() || `${input.sceneLabel} Practice`;
  const recordId = input.id ?? crypto.randomUUID();
  let videoPath: string | null = null;
  if (input.video) {
    if (!input.video.size) throw new Error("녹화 영상이 비어 있습니다. 다시 녹화해 주세요.");
    const extension = input.video.type.includes("mp4") ? "mp4" : "webm";
    videoPath = `${user.id}/${recordId}.${extension}`;
    const { error } = await supabase.storage.from("session-videos").upload(videoPath, input.video, {
      contentType: input.video.type || `video/${extension}`,
      upsert: false,
    });
    if (error) throw new Error(`영상 업로드 실패: ${error.message}`);
  }

  const recordInput = {
    id: recordId,
    user_id: user.id,
    title,
    session_date: sessionDate,
    duration_seconds: input.durationSeconds,
    result: input.result,
    stress_average: input.averageStress,
    diagnosis: input.diagnosis,
    next_action: input.nextAction,
    scene_label: input.sceneLabel,
    timeline: input.timeline,
    video_path: videoPath,
    ...(input.agentReport ? { agent_report: input.agentReport } : {}),
  };
  const { error: recordError } = await supabase.from("presentation_records").insert(recordInput);

  if (recordError) {
    if (videoPath) await supabase.storage.from("session-videos").remove([videoPath]);
    throw new Error(`세션 저장 실패: ${recordError.message}`);
  }

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
      value: input.averageStress.toFixed(2),
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
}

export async function deletePracticeSession(id: string, videoPath: string | null) {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) {
    const remaining = (await loadSessionHistory()).filter((record) => record.id !== id);
    window.localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(remaining));
    return;
  }

  if (videoPath) {
    await supabase.storage.from("session-videos").remove([videoPath]);
  }
  const { error } = await supabase.from("presentation_records").delete().eq("id", id);
  if (error) throw error;
}
