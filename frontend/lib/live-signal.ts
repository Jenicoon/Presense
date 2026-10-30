// Live inference signal — model integration boundary (Progress Report §1.3.5).
//
// The UI depends only on the LiveInferenceFrame shape below. In simulated mode
// values come from a local simulator; live mode sends the capture to the Python
// inference API (Progress Report §2.3, §3.3).

import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export type LiveInferenceFrame = {
  /** Normalized stress level, 0..1 (stress-class probability). */
  stressScore: number;
  /** Max class probability of the binary softmax output, 0.5..1 (Progress Report §2.3). */
  confidence: number;
  timestampMs: number;
  concepts?: Record<string, number>;
  audioFeatures?: Record<string, number | string | boolean>;
  videoFeatures?: Record<string, number | string | boolean>;
  quality?: { faceDetected: boolean; audioValid: boolean };
  modelVersion?: string;
};

export type SignalSource = "simulated" | "live";

// "live" routes frames to the Python inference server (server/); anything else
// uses the built-in simulator. Controlled by env so no code change is needed.
export const SIGNAL_SOURCE: SignalSource =
  process.env.NEXT_PUBLIC_SIGNAL_SOURCE === "live" ? "live" : "simulated";

export const INFERENCE_URL =
  process.env.NEXT_PUBLIC_INFERENCE_URL ?? "http://localhost:8000";

// POST the model's required 16-frame video sequence plus 16 kHz PCM audio.
export async function inferMultimodalFrame(
  frames: Blob[],
  audio: Float32Array,
  task = "Speaking",
  signal?: AbortSignal,
): Promise<LiveInferenceFrame> {
  const supabase = getSupabaseBrowserClient();
  if (!supabase) {
    throw new Error("Live inference requires Supabase authentication.");
  }
  const { data: { session }, error: sessionError } = await supabase.auth.getSession();
  if (sessionError || !session?.access_token) {
    throw new Error("Sign in before using live inference.");
  }

  const form = new FormData();
  frames.forEach((frame, index) => form.append("frames", frame, `frame-${index}.jpg`));
  // Copy into a browser-owned ArrayBuffer: Float32Array.buffer may be a
  // SharedArrayBuffer in newer TypeScript DOM typings, which Blob cannot take.
  const pcm = new Float32Array(audio.length);
  pcm.set(audio);
  form.append("audio", new Blob([pcm.buffer], { type: "application/octet-stream" }), "audio.f32");
  form.append("task", task);
  const res = await fetch(`${INFERENCE_URL}/infer`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session.access_token}` },
    body: form,
    signal,
  });
  if (!res.ok) throw new Error(`Inference failed: ${res.status}`);
  const data = await res.json();
  return {
    stressScore: data.stressScore,
    confidence: data.confidence,
    timestampMs: Date.now(),
    concepts: data.concepts ?? {},
    audioFeatures: data.audioFeatures ?? {},
    videoFeatures: data.videoFeatures ?? {},
    quality: data.quality ?? { faceDetected: false, audioValid: false },
    modelVersion: data.modelVersion,
  };
}

export type LiveSignalController = {
  /** Produce the next inference frame. */
  next: () => LiveInferenceFrame;
  /** Reset internal state at the start of a session. */
  reset: () => void;
};

const START_STRESS = 0.38;

// Random-walk simulator standing in for the trained Student model output.
// This is the ONLY place that fabricates numbers; replace with the real
// backend stream when integrating the model.
export function createSimulatedSignal(): LiveSignalController {
  let stress = START_STRESS;
  return {
    reset() {
      stress = START_STRESS;
    },
    next() {
      stress = Math.max(0.16, Math.min(0.92, stress + (Math.random() - 0.48) * 0.04));
      // Confidence ≈ distance from the 0.5 decision boundary, mapped into 0.6..0.97.
      const confidence = Math.min(0.97, 0.6 + Math.abs(stress - 0.5) * 0.8);
      return { stressScore: stress, confidence, timestampMs: Date.now() };
    },
  };
}
