"use client";
import { useState } from "react";
import { AgentEvidence } from "@/components/agent-observation-report";
import type { AgentReport } from "@/lib/agent-report";
import { measurementLabel } from "@/lib/measurement-labels";
import { clock } from "@/lib/coaching";
export type TimelineCell = {
  startMs: number;
  endMs: number;
  stressScore: number | null;
};
export function withGaps(
  cells: TimelineCell[],
  durationMs: number,
): TimelineCell[] {
  const output: TimelineCell[] = [];
  let end = 0;
  for (const c of [...cells].sort((a, b) => a.startMs - b.startMs)) {
    if (c.startMs > end)
      output.push({ startMs: end, endMs: c.startMs, stressScore: null });
    output.push(c);
    end = c.endMs;
  }
  if (end < durationMs)
    output.push({ startMs: end, endMs: durationMs, stressScore: null });
  return output;
}
export function mergeTimeline(
  cells: TimelineCell[],
  durationMs: number,
): TimelineCell[] {
  if (cells.length <= 120) return cells;
  const result: TimelineCell[] = [];
  for (const c of cells) {
    const last = result[result.length - 1];
    if (
      last &&
      last.endMs === c.startMs &&
      last.stressScore !== null &&
      c.stressScore !== null &&
      c.endMs - last.startMs <= durationMs / 120
    ) {
      last.stressScore =
        (last.stressScore * (last.endMs - last.startMs) +
          c.stressScore * (c.endMs - c.startMs)) /
        (c.endMs - last.startMs);
      last.endMs = c.endMs;
    } else result.push({ ...c });
  }
  return result;
}
export function SessionAgentReport({
  report,
  language,
  onSeek,
}: {
  report: AgentReport;
  language: "ko" | "en";
  onSeek?: (ms: number) => void;
}) {
  const ko = language === "ko";
  const [page, setPage] = useState(0);
  const a = report.analysis;
  const duration = Number(a.durationMs ?? 0);
  const original = (a.timeline ?? []) as TimelineCell[];
  const cells = withGaps(mergeTimeline(original, duration), duration);
  const peak = report.observationReport?.peakSegment;
  const raw = report.rawSegments ?? [];
  const open = (findingId?: string) =>
    window.dispatchEvent(
      new CustomEvent("presense:open-agent", {
        detail: { sessionId: report.sessionId, findingId },
      }),
    );
  return (
    <section
      className="session-agent-report"
      aria-label={ko ? "세션 분석과 코칭" : "Session analysis and coaching"}
    >
      <div className="report-grid">
        <div className="report-card">
          <div className="rc-label">
            {ko ? "실제 분석 시간 / 전체" : "Observed / total"}
          </div>
          <strong>
            {(Number(a.observedMs ?? 0) / 1000).toFixed(1)} /{" "}
            {(duration / 1000).toFixed(1)}s
          </strong>
        </div>
        <div className="report-card">
          <div className="rc-label">
            {ko ? "분석 커버리지" : "Analysis coverage"}
          </div>
          <strong>{Math.round(Number(a.coverage ?? 0) * 100)}%</strong>
        </div>
        <div className="report-card">
          <div className="rc-label">
            {ko ? "사용 / 수집 구간 수" : "Usable / collected windows"}
          </div>
          <strong>
            {Number(a.usableSegmentCount ?? 0)} / {Number(a.segmentCount ?? 0)}
          </strong>
        </div>
        <div className="report-card">
          <div className="rc-label">
            {ko ? "평균 / 최고 모델 점수" : "Mean / peak model score"}
          </div>
          <strong>
            {typeof a.averageStress === "number"
              ? a.averageStress.toFixed(3)
              : "—"}{" "}
            / {typeof a.peakStress === "number" ? a.peakStress.toFixed(3) : "—"}
          </strong>
          {peak && (
            <div>
              {clock(peak.startMs)}–{clock(peak.endMs)}
            </div>
          )}
        </div>
      </div>
      {report.coachingAvailable === false ? (
        <p role="status">
          {ko
            ? "코칭 결과를 저장할 수 없습니다. 연결을 확인한 후 보고서를 다시 생성해 주세요."
            : "Coaching could not be saved. Check the connection and regenerate the report."}
        </p>
      ) : (
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => open(report.priorities[0]?.id)}
        >
          {report.priorities[0]
            ? ko
              ? "우선 확인할 구간과 다음 연습 보기"
              : "Review the priority interval and next exercise"
            : ko
              ? "코치와 이번 세션 살펴보기"
              : "Review this session with the coach"}
        </button>
      )}
      {report.previousCoaching && (
        <p>
          {ko ? "이전 발표에서 선택한 목표: " : "Previously selected goal: "}
          {report.previousCoaching.goalLabel.split(" / ")[ko ? 0 : 1] ??
            report.previousCoaching.goalLabel}
          {!report.previousCoaching.comparable &&
            (ko
              ? " · 분석 기준 또는 환경이 달라 수치 비교를 보류합니다."
              : " · Different versions or scenes prevent a numerical comparison.")}
        </p>
      )}
      <h3>
        {ko ? "시간별 모델 스트레스 신호" : "Model stress signal over time"}
      </h3>
      <figure className="stress-line-chart">
        <svg
          viewBox="0 0 650 220"
          role="img"
          aria-label={
            ko ? "실제 관측 구간별 모델 점수" : "Model scores at observed times"
          }
        >
          {[0, 0.25, 0.5, 0.75, 1].map((v) => (
            <g key={v}>
              <line
                x1="40"
                x2="630"
                y1={180 - v * 160}
                y2={180 - v * 160}
                className="stress-line-grid"
              />
              <text x="4" y={184 - v * 160} className="stress-line-label">
                {v}
              </text>
            </g>
          ))}
          {cells.map((c, i) =>
            c.stressScore === null ? (
              <rect
                key={i}
                x={40 + (c.startMs / Math.max(duration, 1)) * 590}
                y="20"
                width={((c.endMs - c.startMs) / Math.max(duration, 1)) * 590}
                height="160"
                fill="var(--border)"
                opacity=".35"
              >
                <title>
                  {clock(c.startMs)}–{clock(c.endMs)} ·{" "}
                  {ko ? "분석 자료 없음" : "No analysis data"}
                </title>
              </rect>
            ) : (
              <line
                key={i}
                x1={40 + (c.startMs / Math.max(duration, 1)) * 590}
                x2={40 + (c.endMs / Math.max(duration, 1)) * 590}
                y1={180 - c.stressScore * 160}
                y2={180 - c.stressScore * 160}
                className="stress-line-path"
              />
            ),
          )}
          <text x="40" y="210" className="stress-line-label">
            00:00
          </text>
          <text x="580" y="210" className="stress-line-label">
            {clock(duration)}
          </text>
        </svg>
      </figure>
      <div className="video-timeline actual-timeline">
        {cells.map((c, i) => (
          <button
            key={i}
            type="button"
            disabled={c.stressScore === null || !onSeek}
            className={
              c.stressScore === null
                ? "gap"
                : c.stressScore >= 0.7
                  ? "high"
                  : c.stressScore >= 0.5
                    ? "mid"
                    : "low"
            }
            style={{ flex: c.endMs - c.startMs }}
            onClick={() => onSeek?.(c.startMs)}
            title={`${clock(c.startMs)}–${clock(c.endMs)} · ${c.stressScore === null ? (ko ? "분석 자료 없음" : "No analysis data") : c.stressScore.toFixed(3)}`}
            aria-label={`${clock(c.startMs)}–${clock(c.endMs)} ${c.stressScore === null ? (ko ? "분석 자료 없음" : "No analysis data") : c.stressScore.toFixed(3)}`}
          />
        ))}
      </div>
      <p className="signal-note">
        {ko
          ? "회색은 분석 자료가 없는 시간입니다. 구간을 누르면 영상으로 이동합니다. 겹친 시간은 한 번만 반영하며, 같은 시간의 여러 점수는 평균합니다. 낮은 점수도 모두 표시합니다."
          : "Gray means no analysis data. Select an interval to seek the video. Overlap counts once; concurrent scores are averaged. Low scores remain visible."}
      </p>
      {original.length > 120 && (
        <p>
          {ko
            ? "많은 관측 구간은 시간을 묶어 표시합니다. 원본 결과는 아래에서 모두 확인할 수 있습니다."
            : "Dense observations are grouped by time. Every original result remains available below."}
        </p>
      )}
      <p className="signal-note">
        {ko
          ? "도입·전개·핵심·마무리는 시간을 나눈 표시 구간입니다."
          : "Open / Build / Core / Close are display divisions of time."}
      </p>
      <h3>{ko ? "주요 발견과 다음 행동" : "Findings and next action"}</h3>
      {report.priorities.length === 0 ? (
        <p>
          {Number(a.coverage ?? 0) < 0.5
            ? ko
              ? "분석 자료가 부족해 주요 문제를 판단하지 않았습니다."
              : "Insufficient analysis data to judge major issues."
            : ko
              ? "이번 세션에서는 반복적으로 확인된 주요 문제를 찾지 못했습니다."
              : "No repeatedly observed major issue was found in this session."}
        </p>
      ) : (
        report.priorities.slice(0, 3).map((f) => (
          <article key={f.id} className="coach-card coach-data">
            <h4>{f.label.split(" / ")[ko ? 0 : 1] ?? f.label}</h4>
            <p>{f.observationText}</p>
            <p>
              {ko ? "독립 관측" : "Independent observations"}:{" "}
              {f.independentObservations ??
                f.assessment?.independentObservations ??
                "—"}
            </p>
            {f.observations?.map((o) => (
              <div key={o.segmentId}>
                <button
                  className="btn btn-outline"
                  type="button"
                  disabled={!onSeek}
                  onClick={() => onSeek?.(o.startMs)}
                >
                  ▶ {clock(o.startMs)}–{clock(o.endMs)}
                </button>
                <small>
                  {" "}
                  {measurementLabel(f.metric ?? "", ko)}: {o.value} ·{" "}
                  {ko ? "모델 점수" : "Model score"}: {o.stressScore} ·{" "}
                  {Object.entries(o.conceptValues)
                    .map(
                      ([k, v]) => `${measurementLabel(k, ko)}: ${v.toFixed(3)}`,
                    )
                    .join(" · ")}
                </small>
              </div>
            ))}
            <p>
              {f.reviewAction ||
                (ko
                  ? "영상에서 의도한 강조와 실제 전달이 일치하는지 확인하세요."
                  : "Check whether the recorded delivery matches your intended emphasis.")}
            </p>
            <p>
              {f.practiceSuggestion ||
                (ko
                  ? "같은 내용을 30초 다시 발표하고 같은 측정값을 비교해 보세요. 높거나 낮다는 이유만으로 음성·표정을 교정할 필요는 없습니다."
                  : "Repeat the same content for 30 seconds and compare the same measurements. Higher or lower outputs alone do not require correction.")}
            </p>
            <AgentEvidence report={report} ids={f.evidenceIds} ko={ko} />
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => open(f.id)}
            >
              {ko ? "코치와 이 부분 연습하기" : "Practice this with the coach"}
            </button>
          </article>
        ))
      )}
      <button type="button" className="btn btn-outline" onClick={() => open()}>
        {ko ? "AI 코칭 이어가기" : "Continue AI coaching"}
      </button>
      {raw.length > 0 && (
        <details>
          <summary>
            {ko
              ? `실제 분석 결과 ${raw.length}개 확인`
              : `Inspect ${raw.length} original analysis windows`}
          </summary>
          {raw.slice(page * 30, (page + 1) * 30).map((s) => (
            <p key={s.segmentId}>
              {clock(s.startMs)}–{clock(s.endMs)} · {s.stressScore.toFixed(3)} ·{" "}
              {ko ? "분석 신뢰도" : "Confidence"}{" "}
              {s.predictionConfidence?.toFixed(3) ?? "—"} ·{" "}
              {s.quality.audioValid
                ? ko
                  ? "음성 유효"
                  : "Audio valid"
                : ko
                  ? "음성 자료 부족"
                  : "Audio unavailable"}{" "}
              /{" "}
              {s.quality.faceDetected
                ? ko
                  ? "얼굴 검출"
                  : "Face detected"
                : ko
                  ? "얼굴 자료 부족"
                  : "Face unavailable"}
            </p>
          ))}
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            ←
          </button>{" "}
          {page + 1} / {Math.ceil(raw.length / 30)}{" "}
          <button
            disabled={(page + 1) * 30 >= raw.length}
            onClick={() => setPage((p) => p + 1)}
          >
            →
          </button>
        </details>
      )}
    </section>
  );
}
