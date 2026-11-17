import type { LiveInferenceFrame } from "@/lib/live-signal";

export type CalibrationSample = { capturedAtMs: number; stressScore: number };
export type PersonalCalibration = {
  score: number;
  sampleCount: number;
  modelVersion: string;
  calibratedAt: string;
  lastPromptedAt?: string | null;
};

const WINDOW_MS = 10_000;

export function addCalibrationSample(samples: CalibrationSample[], frame: LiveInferenceFrame, capturedAtMs: number): CalibrationSample[] {
  if (samples.length >= 3 || !Number.isFinite(frame.stressScore) || frame.stressScore < 0 || frame.stressScore > 1 ||
      !frame.quality?.audioValid || !frame.quality.faceDetected ||
      !Number.isFinite(capturedAtMs) ||
      (samples.length > 0 && capturedAtMs - samples[samples.length - 1].capturedAtMs < WINDOW_MS)) return samples;
  return [...samples, { capturedAtMs, stressScore: frame.stressScore }];
}

export function calibrationMedian(samples: CalibrationSample[]): number | null {
  if (samples.length < 3) return null;
  const values = samples.slice(0, 3).map((sample) => sample.stressScore).sort((a, b) => a - b);
  const middle = Math.floor(values.length / 2);
  return values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2;
}

export type DriftObservation = { score: number | null; coverage: number; sceneLabel: string; modelVersion: string; sessionDate: string };

export function suggestRecalibration(rows: DriftObservation[], calibration: PersonalCalibration, sceneLabel: string): boolean {
  const calibratedAt = Date.parse(calibration.calibratedAt);
  const promptedAt = calibration.lastPromptedAt ? Date.parse(calibration.lastPromptedAt) : -Infinity;
  const comparable = rows.filter((row) => row.sceneLabel === sceneLabel && row.modelVersion === calibration.modelVersion &&
    row.coverage >= .5 && row.score !== null && Number.isFinite(row.score) && row.score >= 0 && row.score <= 1 &&
    Date.parse(row.sessionDate) > calibratedAt && Date.parse(row.sessionDate) > promptedAt);
  if (comparable.length < 3) return false;
  const latest = [...comparable].sort((a, b) => Date.parse(b.sessionDate) - Date.parse(a.sessionDate)).slice(0, 3);
  return latest.every((row) => Math.abs(row.score! - calibration.score) >= .15 &&
    Math.sign(row.score! - calibration.score) === Math.sign(latest[0].score! - calibration.score));
}


export function reusableCalibration(value: PersonalCalibration | null, modelVersion: string): value is PersonalCalibration {
  return !!value && !!modelVersion && value.modelVersion === modelVersion &&
    Number.isFinite(value.score) && value.score >= 0 && value.score <= 1 &&
    Number.isInteger(value.sampleCount) && value.sampleCount >= 3 &&
    Number.isFinite(Date.parse(value.calibratedAt));
}
