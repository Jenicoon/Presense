"use client";

import { useEffect, useRef, useState } from "react";
import { fixWebmDuration } from "@fix-webm-duration/fix";
import type { PracticeMethodId, PracticeInstructions } from "@/lib/practice-experiments";
import { RECORDING_CONSTRAINTS, RECORDING_OPTIONS } from "@/lib/session-upload";
import { measurePracticeRecording, comparePracticeMeasurement } from "@/lib/practice-measurements";
import { measurementLabel } from "@/lib/measurement-labels";
import { clock } from "@/lib/coaching";
import { loadReportPractice, saveReportPractice, type PracticePreference, type SavedReportPractice } from "@/lib/report-practice-storage";

type Phase = "loading" | "ready" | "permission" | "recording" | "saving";
export function ReportPractice({ sessionId, findingId, interval, videoUrl, ko, pauseReportVideo, strategyId, instructions, onBusyChange, measurementReference }: {
  sessionId: string;
  findingId: string;
  interval: { startMs: number; endMs: number };
  videoUrl: string;
  pauseReportVideo?: () => void;
  ko: boolean;
  strategyId: PracticeMethodId;
  instructions: PracticeInstructions;
  onBusyChange?: (busy: boolean) => void;
  measurementReference?: { modelVersion?: string; metricDefinitionVersion?: string; conceptDefinitionVersion?: string; modality: string; metric: string; value: number };
}) {
  const { startMs, endMs } = interval;
  const storageKey = JSON.stringify([sessionId, findingId, startMs, endMs]);
  const methodId = strategyId;
  const method = { ...instructions, label: instructions.goal };
  const planKey = JSON.stringify(instructions);
  const original = useRef<HTMLVideoElement>(null);
  const retry = useRef<HTMLVideoElement>(null);
  const preview = useRef<HTMLVideoElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const camera = useRef<MediaStream | null>(null);
  const stopTimer = useRef<number | undefined>(undefined);
  const lifetime = useRef(0);
  const [phase, setPhase] = useState<Phase>("loading");
  const [attempt, setAttempt] = useState<SavedReportPractice | null>(null);
  const [retryUrl, setRetryUrl] = useState("");
  const [error, setError] = useState<"camera" | "play" | "record" | "storage" | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [measurementError, setMeasurementError] = useState(false);
  const [playing, setPlaying] = useState<"original" | "retry" | null>(null);
  const [hasPlayed, setHasPlayed] = useState({ original: false, retry: false });
  const busy = phase !== "ready";

  useEffect(() => {
    const generation = ++lifetime.current;
    void loadReportPractice(storageKey).then(saved => {
      if (lifetime.current === generation) {
        setAttempt(saved?.strategyId === methodId && saved.planKey === planKey ? saved : null);
      }
    }).catch(() => {
      if (lifetime.current === generation) setError("storage");
    }).finally(() => {
      if (lifetime.current === generation) setPhase("ready");
    });
    return () => {
      lifetime.current++;
      window.clearTimeout(stopTimer.current);
      if (recorder.current?.state === "recording") recorder.current.stop();
      camera.current?.getTracks().forEach(track => track.stop());
      camera.current = null;
      recorder.current = null;
    };
  }, [storageKey, methodId, planKey]);

  useEffect(() => { onBusyChange?.(phase === "recording" || phase === "permission" || phase === "saving"); }, [phase, onBusyChange]);
  const recording = attempt?.recording;
  useEffect(() => {
    const url = recording ? URL.createObjectURL(recording) : "";
    setRetryUrl(url);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [recording]);

  useEffect(() => {
    if (phase === "recording" && preview.current) preview.current.srcObject = camera.current;
  }, [phase]);

  function stopRecording() {
    const take = recorder.current;
    if (take?.state === "recording") {
      setPhase("saving");
      take.stop();
    }
  }

  async function startRecording() {
    if (busy || measuring || recorder.current) return;
    setError(null);
    pauseReportVideo?.();
    original.current?.pause();
    retry.current?.pause();
    const generation = lifetime.current;
    setPhase("permission");
    let stream: MediaStream | undefined;
    try {
      stream = await navigator.mediaDevices.getUserMedia(RECORDING_CONSTRAINTS);
      if (lifetime.current !== generation) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      camera.current = stream;
      const take = new MediaRecorder(stream, RECORDING_OPTIONS);
      const chunks: Blob[] = [];
      let failed = false;
      take.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      take.onerror = () => { failed = true; };
      take.onstop = async () => {
        window.clearTimeout(stopTimer.current);
        stream?.getTracks().forEach(track => track.stop());
        if (lifetime.current !== generation) return;
        setPhase("saving");
        camera.current = null;
        const duration = performance.now() - started;
        let blob = new Blob(chunks, { type: take.mimeType || chunks[0]?.type });
        if (failed || !blob.size || duration < 1000) {
          setError("record");
        } else {
          if (blob.type.includes("webm")) {
            try { blob = await fixWebmDuration(blob, duration, { logger: false }); }
            catch { /* The original recording can still be played. */ }
          }
          if (lifetime.current !== generation) return;
          const next = { recording: blob, preference: null, strategyId: methodId, planKey, durationMs: duration };
          setAttempt(next);
          setHasPlayed(current => ({ ...current, retry: false }));
          try { await saveReportPractice(storageKey, next); }
          catch { if (lifetime.current === generation) setError("storage"); }
        }
        if (lifetime.current !== generation) return;
        recorder.current = null;
        setPhase("ready");
      };
      const started = performance.now();
      take.start();
      recorder.current = take;
      setPhase("recording");
      stopTimer.current = window.setTimeout(stopRecording, 30_000);
    } catch {
      stream?.getTracks().forEach(track => track.stop());
      if (lifetime.current !== generation) return;
      camera.current = null;
      setError(stream ? "record" : "camera");
      setPhase("ready");
    }
  }

  async function play(which: "original" | "retry") {
    const player = which === "original" ? original.current : retry.current;
    if (!player || busy) return;
    const generation = lifetime.current;
    (which === "original" ? retry : original).current?.pause();
    setError(null);
    player.currentTime = which === "original" ? startMs / 1000 : 0;
    try { await player.play(); }
    catch { if (lifetime.current === generation) setError("play"); }
  }

  function played(which: "original" | "retry") {
    pauseReportVideo?.();
    (which === "original" ? retry : original).current?.pause();
    setPlaying(which);
    setHasPlayed(current => ({ ...current, [which]: true }));
  }

  async function choose(preference: PracticePreference) {
    if (!attempt || busy) return;
    const generation = lifetime.current;
    const next = { ...attempt, preference };
    setAttempt(next);
    setError(null);
    setPhase("saving");
    try { await saveReportPractice(storageKey, next); }
    catch { if (lifetime.current === generation) setError("storage"); }
    finally { if (lifetime.current === generation) setPhase("ready"); }
  }

  async function measure() {
    if (!attempt || measuring || !attempt.durationMs) return;
    const generation = lifetime.current;
    setMeasuring(true); setMeasurementError(false);
    try {
      const measurement = await measurePracticeRecording(attempt.recording, attempt.durationMs);
      if (generation !== lifetime.current) return;
      const next = { ...attempt, measurement };
      setAttempt(next); await saveReportPractice(storageKey, next);
    } catch { if (generation === lifetime.current) setMeasurementError(true); }
    finally { if (generation === lifetime.current) setMeasuring(false); }
  }
  const numeric = measurementReference && attempt?.measurement && attempt.conditionsConfirmed
    ? comparePracticeMeasurement(measurementReference, attempt.measurement) : null;

  const options: [PracticePreference, string][] = [
    ["original", ko ? "원본" : "Original"],
    ["retry", ko ? "다시 녹화한 버전" : "New take"],
    ["same", ko ? "비슷해요" : "About the same"],
  ];
  const errors = {
    camera: ko ? "카메라와 마이크를 열 수 없어요. 브라우저 권한을 확인하고 다시 시도해 주세요." : "Could not open your camera and microphone. Check browser permissions and try again.",
    play: ko ? "영상을 재생할 수 없어요. 다시 시도해 주세요." : "Could not play the recording. Please try again.",
    record: ko ? "녹화가 완료되지 않았어요. 한 문장을 끝까지 말한 뒤 다시 확인해 주세요." : "The recording did not complete. Try recording one full sentence.",
    storage: ko ? "이 브라우저에 연습을 저장할 수 없어요." : "This browser could not save the practice.",
  };

  return <section className="review-inline-practice" aria-label={ko ? "짧게 연습하고 비교하기" : "Rehearse and compare"}>
    <h5>{ko ? "짧게 연습하고 비교하기" : "Rehearse and compare"}</h5>
    <strong>{method.goal}</strong>
    <p>{method.reason}</p>
    <details className="review-details"><summary>{ko ? "연습 순서 보기" : "View practice steps"}</summary><ol className="review-practice-steps">{method.steps.map(step => <li key={step}>{step}</li>)}</ol></details>
    <p className="review-practice-criterion"><strong>{ko ? "비교 기준" : "Compare using this question"}</strong><br />{method.question}</p>
    <div className="review-practice-players">
      <div>
        <video ref={original} src={videoUrl} preload="metadata" playsInline
          onPlaying={() => played("original")} onPause={() => setPlaying(current => current === "original" ? null : current)}
          onTimeUpdate={event => {
            if (event.currentTarget.currentTime >= endMs / 1000) event.currentTarget.pause();
          }}
          onError={() => setError("play")} />
        <button type="button" className="btn btn-outline" disabled={busy}
          onClick={() => playing === "original" ? original.current?.pause() : void play("original")}>
          {playing === "original" ? (ko ? "원본 일시 정지" : "Pause original") : (ko ? "원본 구간 듣기" : "Play original interval")} · {clock(startMs)}–{clock(endMs)}
        </button>
      </div>
      {(retryUrl || phase === "recording") && <div>
        {phase === "recording" ? <video ref={preview} autoPlay muted playsInline /> : <>
          <video key={retryUrl} ref={retry} src={retryUrl} preload="metadata" playsInline controls
            onPlaying={() => played("retry")} onPause={() => setPlaying(current => current === "retry" ? null : current)}
            onError={() => setError("play")} />
          <button type="button" className="btn btn-outline" disabled={busy}
            onClick={() => playing === "retry" ? retry.current?.pause() : void play("retry")}>
            {playing === "retry" ? (ko ? "재녹화 일시 정지" : "Pause new take") : (ko ? "재녹화 듣기" : "Play new take")}
          </button>
        </>}
      </div>}
    </div>
    <div className="review-practice-actions">
      {phase === "recording" ? <button type="button" className="btn btn-primary" onClick={stopRecording}>{ko ? "녹화 끝내기" : "Finish recording"}</button>
        : <button type="button" className="btn btn-primary" disabled={busy || (!hasPlayed.original && !attempt)} onClick={() => void startRecording()}>
          {attempt ? (ko ? "다시 시도하기" : "Record another take") : (ko ? "같은 문장 녹화" : "Record the same sentence")}
        </button>}
      {phase !== "ready" && <small role="status">{phase === "permission" ? (ko ? "카메라와 마이크를 여는 중…" : "Opening the camera and microphone…")
        : phase === "recording" ? (ko ? "녹화 중 · 최대 30초" : "Recording · up to 30 seconds")
        : (ko ? "저장 중…" : "Saving…")}</small>}
    </div>
    {attempt && phase !== "recording" && measurementReference && <details className="review-details" aria-label={ko ? "측정값 비교" : "Measurement comparison"}>
      <summary>{ko ? "측정값 비교" : "Measurement comparison"}</summary>
      <label><input type="checkbox" checked={attempt.conditionsConfirmed ?? false} disabled={measuring}
        onChange={event => { const next = { ...attempt, conditionsConfirmed: event.target.checked }; setAttempt(next); void saveReportPractice(storageKey, next).catch(() => setError("storage")); }} />
        {ko ? "원본과 같은 문장·촬영 환경으로 녹화했어요" : "I used the same sentence and recording setup"}</label>
      {!attempt.measurement && <button className="btn btn-outline" type="button" disabled={measuring || busy || !attempt.conditionsConfirmed || (attempt.durationMs ?? 0) < 10000} onClick={() => void measure()}>
        {measuring ? (ko ? "측정 중…" : "Measuring…") : (ko ? "재녹화 측정값 비교" : "Compare new take measurements")}</button>}
      {(attempt.durationMs ?? 0) < 10000 && <p>{ko ? "수치 비교에는 음성이 포함된 10초 이상의 녹화가 필요해요. 영상으로는 비교할 수 있습니다." : "Numerical comparison needs at least ten seconds with audio. Video self-review is still available."}</p>}
      {numeric && <><p>{measurementLabel(measurementReference.metric, ko)}</p><table className="data-table"><thead><tr><th>{ko ? "원본" : "Original"}</th><th>{ko ? "재녹화" : "New take"}</th><th>{ko ? "변화" : "Difference"}</th></tr></thead><tbody><tr><td>{numeric.original.toFixed(3)}</td><td>{numeric.retry.toFixed(3)}</td><td>{numeric.difference > 0 ? "+" : ""}{numeric.difference.toFixed(3)}</td></tr></tbody></table></>}
      {attempt.measurement && !numeric && <p>{ko ? "분석 조건과 측정 품질이 맞는 경우에만 수치를 비교합니다." : "Numerical comparison requires matching analysis versions and usable measurements."}</p>}
      {measurementError && <p role="alert" className="error-msg">{ko ? "재녹화 측정을 완료하지 못했어요. 영상은 보관되어 있으며 측정만 다시 시도할 수 있습니다." : "New-take measurement failed. The video is retained; you can retry only the measurement."}</p>}
      <p>{ko ? "수치 변화는 전달력의 개선 판정이 아닙니다. 아래에서 영상을 보고 직접 평가하세요." : "A numerical change does not establish better delivery. Review the videos and make your own assessment below."}</p>
    </details>}
    {attempt && phase !== "recording" && <fieldset className="review-practice-choice" disabled={busy || (!attempt.preference && (!hasPlayed.original || !hasPlayed.retry))}>
      <legend>{ko ? "영상으로 확인한 나의 평가" : "My video-based assessment"} · {method.question}</legend>
      <div className="review-practice-actions">{options.map(([value, label]) => <button type="button" key={value}
        className={attempt.preference === value ? "btn btn-primary" : "btn btn-outline"}
        aria-pressed={attempt.preference === value} onClick={() => void choose(value)}>{label}</button>)}</div>
      {!attempt.preference && (!hasPlayed.original || !hasPlayed.retry) && <small>{ko ? "두 버전을 재생한 뒤 선택하세요." : "Play both versions, then choose."}</small>}
    </fieldset>}
    {attempt?.preference && phase !== "recording" && <div className="review-practice-result" role="status">
      <strong>{ko ? "나의 비교 결과" : "Your comparison"}</strong>
      <p>{attempt.preference === "retry" ? (ko ? `재녹화한 방식을 선택했어요. 다음 발표에서도 ‘${method.label}’ 연습을 적용해 보세요.` : `You chose the new take. Try “${method.label}” in your next presentation.`)
        : attempt.preference === "original" ? (ko ? "원본 방식을 선택했어요. 이 문장은 기존 전달을 유지해 보세요." : "You chose the original. Keep that delivery for this sentence.")
        : (ko ? "두 버전이 비슷했어요. 같은 문장으로 한 번 더 연습해 보세요." : "Both versions felt similar. Try the same sentence once more.")}</p>
    </div>}
    {error && <p className="error-msg" role="alert">{errors[error]}</p>}
  </section>;
}
