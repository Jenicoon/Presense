"use client";
import { ArrowRight, Play, Target, Video } from "lucide-react";
import { signalScore } from "@/lib/report-locale";
import { measurementLabel } from "@/lib/measurement-labels";
import {
  clock,
  jumpToVideo,
  type CoachAction,
  type CoachActionContext,
  type CoachComponent,
} from "@/lib/coaching";
const outcome: Record<string, [string, string]> = {
  review_required: ["촬영 완료 · 전달 확인", "Take ready · review delivery"],
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
  onAction: (action: CoachAction, findingId?: string, context?: CoachActionContext) => void;
}) {
  return (
    <div className="coach-components">
      {components.map((c, i) => {
        switch (c.type) {
          case "coaching_path":
            return <article key={i} className="coach-card coach-next-action"><span className="coach-component-heading">{ko ? "다음 행동" : "Next action"}</span><strong>{c.title}</strong><p>{c.instruction}</p></article>;
          case "review_guide":
            return <article key={i} className="coach-card coach-review-guide"><strong>{c.title}</strong><ol>{c.steps.map((step,index)=><li key={index}>{step}</li>)}</ol></article>;
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
                      onAction(choice.action, choice.findingId ?? undefined, {reviewOutcome: choice.reviewOutcome, practiceStrategyId: choice.practiceStrategyId})
                    }
                  >
                    {choice.label}
                  </button>
                ))}
              </div>
            );
          case "video_segment":
            if (c.findingId) {
              const group = components.filter((item): item is Extract<CoachComponent, {type: "video_segment"}> => item.type === "video_segment" && item.findingId === c.findingId);
              if (components.findIndex(item => item.type === "video_segment" && item.findingId === c.findingId) !== i) return null;
              return <section key={i} className="coach-observation-group" aria-label={ko ? `확인할 영상 ${group.length}곳` : `${group.length} intervals to review`}>
                <strong>{ko ? `확인할 영상 ${group.length}곳` : `${group.length} intervals to review`}</strong>
                <p>{ko ? "아래 시간을 눌러 해당 장면을 다시 보세요." : "Select a time to replay that part of the recording."}</p>
                <div className="coach-observation-grid">{group.map((part, index) => <button key={`${part.sessionId}:${part.startMs}:${part.endMs}`} type="button" className="coach-card coach-video" aria-label={ko ? `영상 ${index+1}: ${clock(part.startMs)}–${clock(part.endMs)}` : `Clip ${index+1}: ${clock(part.startMs)}–${clock(part.endMs)}`} onClick={() => jumpToVideo(part.sessionId, part.startMs)}>
                  <span className="coach-video-icon"><Play size={14} /></span><span><strong>{ko ? `영상 ${index+1}` : `Clip ${index+1}`}</strong><small>{clock(part.startMs)}–{clock(part.endMs)}</small></span><ArrowRight size={13} />
                </button>)}</div>
              </section>;
            }
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
                <div className="coach-practice-steps">{c.instruction.split("\n").map((step, index) => <p key={index}>{step}</p>)}</div>
                <div className="coach-success-check"><strong>{ko ? "연습 후 확인할 것" : "What to check after practice"}</strong><p>{c.criterion}</p></div>
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
                {r.assessmentSource === "presenter" && <p className="coach-assessment-source">{ko ? "영상을 보고 직접 확인한 내 평가" : "Your own review of the recording"}</p>}
                <p>
                  {r.scope === "practice"
                    ? ko
                      ? "선택한 원본 구간 → 이번 재촬영"
                      : "Selected original interval → retry"
                    : ko
                      ? "이전 발표 → 이번 발표"
                      : "Previous presentation → current presentation"}
                </p>
                <div className="coach-score-comparison">{[r.before, r.after].map((take, index) => <div key={index}><span>{index === 0 ? (ko ? "이전 시도" : "Before") : ko ? "이번 시도" : "Current"}</span><strong>{signalScore(take.value)}</strong><small>{ko ? "스트레스 신호" : "Stress signal"}</small></div>)}</div>
                {r.modelScoreChange !== null && <p className="coach-score-change">{ko ? "스트레스 신호 변화" : "Stress signal change"} <strong>{r.modelScoreChange > 0 ? "+" : ""}{Math.round(r.modelScoreChange * 100)}{ko ? "점" : " points"}</strong></p>}
                <details className="review-details"><summary>{ko ? "분석 자료와 수치 변화 자세히 보기" : "Inspect data quality and measurement changes"}</summary>
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
                </details>
                <details className="review-details"><summary>{ko ? "평가 기준" : "Evaluation criteria"}</summary><p>{r.evaluationMode === "delivery_review"
                  ? ko ? "스트레스 신호와 측정값은 변화만 보여줍니다. 성공 여부는 영상을 보고 선택한 전달 행동을 실행했는지 직접 확인해 기록합니다. 숫자가 낮아졌다는 이유로 달성을 부여하지 않습니다. 수치 비교에는 각 시도의 독립 관측 2개, 커버리지 50%, 측정 품질 80%와 같은 분석 조건이 필요합니다." : "Signals and measurements describe changes. Review the recording to assess whether you carried out your delivery action. Lower numbers alone do not earn an achieved result. Numerical comparison requires matching conditions, 2 independent observations, 50% coverage and 80% measurement quality per take."
                  : r.scope === "previous_session" ? (ko ? "같은 환경과 분석 기준에서 관측한 값만 비교합니다. 점수 변화로 발표 실력의 향상을 판정하지 않습니다." : "Only measurements from matching scenes and analysis versions are compared. Score changes do not grade delivery.")
                  : ko ? "이전 버전의 수치 기준 결과입니다. 기준값과의 편차 감소율 = 1 − |현재−기준| ÷ |이전−기준|. 이 결과는 전달력 평가가 아닙니다." : "Legacy measurement-based result: deviation reduction = 1 − |current−reference| / |previous−reference|. This does not assess delivery quality."}</p></details>
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
