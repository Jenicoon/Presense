import { inferMultimodalFrame, type LiveInferenceFrame } from "@/lib/live-signal";

/** Analyze one real ten-second window with the existing inference service.
 * Media stays on the existing inference boundary; this never calls Luxia.
 */
export async function measurePracticeRecording(recording: Blob, durationMs: number): Promise<LiveInferenceFrame> {
  if (durationMs < 10_000) throw new Error("short_recording");
  const url = URL.createObjectURL(recording);
  const video = document.createElement("video");
  video.muted = true; video.playsInline = true; video.preload = "auto";
  const audio = new AudioContext();
  function event(name: "loadedmetadata" | "seeked") {
    return new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => { cleanup(); reject(new Error("media_timeout")); }, 15_000);
      const cleanup = () => { window.clearTimeout(timeout); video.removeEventListener(name, success); video.removeEventListener("error", failure); };
      const success = () => { cleanup(); resolve(); };
      const failure = () => { cleanup(); reject(new Error("media_decode")); };
      video.addEventListener(name, success, { once: true }); video.addEventListener("error", failure, { once: true });
    });
  }
  try {
    const decoded = await audio.decodeAudioData(await recording.arrayBuffer());
    if (decoded.duration < 10) throw new Error("short_audio");
    const loaded = event("loadedmetadata"); video.src = url; await loaded;
    const canvas = document.createElement("canvas"); canvas.width = 320; canvas.height = 180;
    const context = canvas.getContext("2d"); if (!context) throw new Error("canvas_unavailable");
    const end = Math.min(durationMs / 1000, decoded.duration, Number.isFinite(video.duration) ? video.duration : Infinity);
    const start = Math.max(0, end - 10);
    const frames: Blob[] = [];
    for (let index = 0; index < 16; index++) {
      const sought = event("seeked"); video.currentTime = start + (index + .5) * (10 / 16); await sought;
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      frames.push(await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error("frame_decode")), "image/jpeg", .8)));
    }
    const samples = new Float32Array(160_000);
    for (let index = 0; index < samples.length; index++) {
      const position = Math.min(decoded.length - 1, Math.floor((start + index / 16000) * decoded.sampleRate));
      for (let channel = 0; channel < decoded.numberOfChannels; channel++) samples[index] += decoded.getChannelData(channel)[position] / decoded.numberOfChannels;
    }
    return await inferMultimodalFrame(frames, samples, "Speaking", AbortSignal.timeout(90_000));
  } finally { video.removeAttribute("src"); video.load(); URL.revokeObjectURL(url); await audio.close(); }
}

export function comparePracticeMeasurement(
  original: { modelVersion?: string; metricDefinitionVersion?: string; conceptDefinitionVersion?: string; modality: string; metric: string; value: number },
  measured: LiveInferenceFrame,
) {
  if (!original.modelVersion || original.modelVersion !== measured.modelVersion
    || original.metricDefinitionVersion !== measured.metricDefinitionVersion
    || original.conceptDefinitionVersion !== measured.conceptDefinitionVersion) return null;
  const valid = original.modality === "audio" ? measured.quality?.audioValid : original.modality === "video" ? measured.quality?.faceDetected : measured.quality?.audioValid && measured.quality.faceDetected;
  const value = (original.modality === "audio" ? measured.audioFeatures : original.modality === "video" ? measured.videoFeatures : measured.concepts)?.[original.metric];
  return valid && typeof value === "number" && Number.isFinite(value)
    ? { original: original.value, retry: value, difference: value - original.value } : null;
}
