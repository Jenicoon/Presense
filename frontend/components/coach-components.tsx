"use client";
import { ArrowRight, Play, Target, Video } from "lucide-react";
import { measurementLabel } from "@/lib/measurement-labels";
import {
  clock,
  jumpToVideo,
  type CoachAction,
  type CoachComponent,
} from "@/lib/coaching";
const outcome: Record<string, [string, string]> = {
  achieved: ["달성", "Achieved"],
  partial: ["부분 달성", "Partly achieved"],
  insufficient_data: ["자료 부족", "Insufficient data"],
  retry_recommended: ["재시도 권장", "Retry recommended"],
  comparable: ["동일 기준 비교", "Comparable measurements"],
};
export function CoachComponents({
  components,
  ko,
  busy,
  onAction,
}: {
  components: CoachComponent[];
  ko: boolean;
  busy: boolean;
  onAction: (action: CoachAction, findingId?: string) => void;
}) {
  return (
    <div className="coach-components">
      {components.map((c, i) => {
        switch (c.type) {
          case "action_choices":
            return (
              <div className="coach-choices" key={i}>
                {c.choices.map((choice) => (
                  <button
                    type="button"
                    className="btn btn-outline"
                    key={choice.id}
                    disabled={busy}
                    onClick={() =>
                      onAction(choice.action, choice.findingId ?? undefined)
                    }
                  >
                    {choice.label}
                  </button>
                ))}
              </div>
            );
          case "video_segment":
            return (
              <button
                key={i}
                type="button"
                className="coach-card coach-video"
                onClick={() => jumpToVideo(c.sessionId, c.startMs)}
              >
                <span className="coach-video-icon"><Play size={16} /></span><span><strong>{c.label}</strong><small>{clock(c.startMs)}–{clock(c.endMs)}</small></span><ArrowRight size={15} />
              </button>
            );
          case "finding":
            return (
              <button
                key={i}
                type="button"
                className="coach-card coach-finding-choice"
                disabled={busy}
                onClick={() => onAction("explain_finding", c.findingId)}
              >
                <Target size={16} /><span>{c.label}</span><ArrowRight size={15} />
              </button>
            );
          case "practice":
            return (
              <article key={i} className="coach-card coach-exercise">
                <div className="coach-component-heading"><span><Video size={14} />{ko ? "연습 과제" : "Practice exercise"}</span><small>{c.durationSeconds}{ko ? "초" : "s"}</small></div>
                <strong>{c.label}</strong>
                <p>{c.instruction}</p>
                <details className="review-details"><summary>{ko ? "어떻게 평가하나요?" : "How is it evaluated?"}</summary><p>{c.criterion}</p></details>
              </article>
            );
          case "insufficient_data":
            return (
              <div key={i} className="coach-card" role="status">
                {c.label}
              </div>
            );
          case "comparison": {
            const r = c.comparison;
            return (
              <article key={i} className="coach-card coach-comparison">
                <strong className="coach-outcome">{outcome[r.outcome]?.[ko ? 0 : 1] ?? r.outcome}</strong>
                <p>
                  {r.scope === "practice"
                    ? ko
                      ? "선택한 원본 구간 → 이번 재촬영"
                      : "Selected original interval → retry"
                    : ko
                      ? "이전 발표 → 이번 발표"
                      : "Previous presentation → current presentation"}
                </p>
                <div className="coach-score-comparison">{[r.before, r.after].map((take, index) => <div key={index}><span>{index === 0 ? (ko ? "이전 시도" : "Before") : ko ? "이번 시도" : "Current"}</span><strong>{take.value?.toFixed(3) ?? "—"}</strong><small>{ko ? "모델 점수" : "Model score"}</small></div>)}</div>
                {r.modelScoreChange !== null && <p className="coach-score-change">{ko ? "모델 점수 변화" : "Model score change"} <strong>{r.modelScoreChange > 0 ? "+" : ""}{r.modelScoreChange.toFixed(3)}</strong></p>}
                <dl className="coach-quality-list">
                  <div><dt>{ko ? "분석 구간" : "Analysis windows"}</dt><dd>{r.before.windowCount} → {r.after.windowCount}</dd></div>
                  <div><dt>{ko ? "독립 관측" : "Independent observations"}</dt><dd>{r.before.independentObservations} → {r.after.independentObservations}</dd></div>
                  <div><dt>{ko ? "커버리지" : "Coverage"}</dt><dd>{Math.round(r.before.coverage * 100)}% → {Math.round(r.after.coverage * 100)}%</dd></div>
                  <div><dt>{ko ? "측정 품질" : "Measurement quality"}</dt><dd>{Math.round(r.before.quality * 100)}% → {Math.round(r.after.quality * 100)}%</dd></div>
                </dl>
                {!r.compatible && (
                  <p>
                    {ko
                      ? "환경 또는 분석 기준이 달라 비교할 수 없습니다."
                      : "Scenes or analysis versions differ; comparison is unavailable."}
                  </p>
                )}
                <div className="observation-table-wrap">
                  <table className="observation-table coach-measurement-table">
                    <thead>
                      <tr>
                        <th>{ko ? "관련 측정값" : "Measurement"}</th>
                        <th>{ko ? "이전" : "Before"}</th>
                        <th>{ko ? "현재" : "After"}</th>
                        <th>Δ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {r.measurements.map((m) => (
                        <tr key={`${m.modality}:${m.metric}`}>
                          <td>
                            {measurementLabel(m.metric, ko)}
                            <small>
                              {" "}
                              · {m.beforeCount} → {m.afterCount} /{" "}
                              {Math.round(m.beforeQuality * 100)}% →{" "}
                              {Math.round(m.afterQuality * 100)}%
                            </small>
                          </td>
                          <td>{m.before.toFixed(3)}</td>
                          <td>{m.after.toFixed(3)}</td>
                          <td>{m.difference.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <details>
                  <summary>
                    {ko
                      ? "평가 기준과 계산식"
                      : "Evaluation criteria and formula"}
                  </summary>
                  <p>
                    {ko
                      ? "기준값과의 편차 감소율 = 1 − |현재−기준| ÷ |이전−기준|. 20% 이상 달성, 0% 초과 부분 달성, 그 외 재시도 권장. 기준값·동일 지표·각 시도 독립 관측 2개·커버리지 50%·측정 품질 80%가 필요합니다. 전달력 향상을 의미하지 않습니다."
                      : "Deviation reduction = 1 − |current−reference| / |previous−reference|. ≥20% achieved, >0 partial, otherwise retry. Requires a reference, same metric, 2 independent windows, 50% coverage and 80% metric quality in each take. This does not establish better delivery."}
                  </p>
                  <p>
                    {ko ? "기준값" : "Reference"}: {r.referenceValue ?? "—"}
                  </p>
                </details>
              </article>
            );
          }
          default:
            return null;
        }
      })}
    </div>
  );
}
