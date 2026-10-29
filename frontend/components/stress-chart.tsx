"use client";
import { useId, useState } from "react";
import { useLang } from "@/lib/i18n";

type TimedScore = { startMs: number; endMs: number; stressScore: number | null };

/** Each continuous run ends at a missing interval; values are never filled in. */
export function timelineRuns(cells: TimedScore[], durationMs: number): TimedScore[][] {
  const runs: TimedScore[][] = [];
  let run: TimedScore[] | undefined;
  for (const cell of [...cells].sort((a, b) => a.startMs - b.startMs)) {
    if (cell.stressScore === null || !Number.isFinite(cell.stressScore) || cell.stressScore < 0 || cell.stressScore > 1 || cell.startMs < 0 || cell.endMs <= cell.startMs || cell.endMs > durationMs) {
      run = undefined;
      continue;
    }
    if (!run || run[run.length - 1].endMs !== cell.startMs) {
      run = [];
      runs.push(run);
    }
    run.push(cell);
  }
  return runs;
}

function time(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function StressChart({ series = [], cells, durationMs = 0, language, onSelect }: {
  series?: number[];
  cells?: TimedScore[];
  durationMs?: number;
  language?: "ko" | "en";
  onSelect?: (ms: number) => void;
}) {
  const { lang } = useLang();
  const ko = (language ?? lang) === "ko";
  const titleId = useId();
  const [selected, setSelected] = useState<TimedScore | null>(null);
  const phases = ko ? ["도입", "전개", "핵심", "마무리"] : ["Open", "Build", "Core", "Close"];
  if (!cells && !series.length) return <p>{ko ? "저장된 구간 데이터가 없습니다." : "No segment data was saved."}</p>;
  const left = 44, top = 20, width = 584, height = 180;
  const duration = Math.max(durationMs, 1);
  const x = (ms: number) => left + ms / duration * width;
  const y = (value: number) => top + height * (1 - value);
  const runs = cells ? timelineRuns(cells, durationMs) : [series.map((value, index) => ({
    startMs: index, endMs: index + 1,
    stressScore: Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0)) / 100,
  }))];
  const pointX = (cell: TimedScore) => cells ? x((cell.startMs + cell.endMs) / 2) : left + (cell.startMs + .5) / series.length * width;
  const label = (cell: TimedScore) => cells
    ? `${time(cell.startMs)}–${time(cell.endMs)} ${Math.round(cell.stressScore! * 100)} / 100`
    : `${phases[Math.min(3, Math.floor(cell.startMs * 4 / series.length))]} · ${cell.startMs + 1}/${series.length}: ${Math.round(cell.stressScore! * 100)}/100`;
  const select = (cell: TimedScore) => { setSelected(cell); onSelect?.(cell.startMs); };
  return <figure className="stress-line-chart">
    <svg viewBox="0 0 650 264" role={onSelect ? "group" : "img"} aria-labelledby={titleId}>
      <title id={titleId}>{ko ? "구간별 스트레스 신호, 0–100" : "Stress signal over the session, 0–100"}</title>
      {[0, 25, 50, 75, 100].map(value => <g key={value}>
        <line className="stress-line-grid" x1={left} x2={left + width} y1={y(value / 100)} y2={y(value / 100)} />
        <text className="stress-line-label" x={left - 10} y={y(value / 100) + 4} textAnchor="end">{value}</text>
      </g>)}
      {cells?.filter(cell => cell.stressScore === null).map(cell => <rect key={cell.startMs} className="stress-line-gap" x={x(cell.startMs)} y={top} width={(cell.endMs - cell.startMs) / duration * width} height={height}>
        <title>{time(cell.startMs)}–{time(cell.endMs)} · {ko ? "분석 자료 없음" : "No analysis data"}</title>
      </rect>)}
      {phases.map((phase, index) => <g key={phase}>
        {index > 0 && <line className="stress-line-divider" x1={left + width * index / 4} x2={left + width * index / 4} y1={top} y2={top + height} />}
        <text className="stress-line-label" x={left + width * (index + .5) / 4} y={226} textAnchor="middle">{phase}</text>
        {cells && <text className="stress-line-time" x={left + width * (index + .5) / 4} y={246} textAnchor="middle">{time(durationMs * index / 4)}–{time(durationMs * (index + 1) / 4)}</text>}
      </g>)}
      {cells && !runs.length && <text className="stress-line-label" x={left + width / 2} y={top + height / 2} textAnchor="middle">{ko ? "분석 자료 없음" : "No analysis data"}</text>}
      {runs.map((run, index) => <polyline key={index} className="stress-line-path" points={run.map(cell => `${pointX(cell)},${y(cell.stressScore!)}`).join(" ")} />)}
      {runs.flat().map(cell => <g key={cell.startMs} role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined} aria-label={onSelect ? label(cell) : undefined} className={`stress-line-control${selected?.startMs === cell.startMs ? " selected" : ""}`} onClick={onSelect ? () => select(cell) : undefined} onKeyDown={onSelect ? event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(cell); } } : undefined}>
        <title>{label(cell)}</title>
        <circle className="stress-line-hit" cx={pointX(cell)} cy={y(cell.stressScore!)} r="12" />
        <circle className="stress-line-point" cx={pointX(cell)} cy={y(cell.stressScore!)} r="4" />
      </g>)}
    </svg>
    <figcaption>{cells ? (ko ? "가로축: 녹화 시간 · 세로축: 스트레스 신호 (0–100). 네 구간은 시간을 나눈 표시입니다." : "Horizontal: recording time · Vertical: stress signal (0–100). The four sections are time divisions.") : (ko ? "가로축: 연습 진행 구간 · 세로축: 모델 점수 (0–100)" : "Horizontal: session progress · Vertical: model score (0–100)")}</figcaption>
    {selected && onSelect && <p className="stress-line-selection" role="status">{label(selected)} · {ko ? "이 시점으로 이동했어요" : "Jumped to this moment"}</p>}
  </figure>;
}
