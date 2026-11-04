import { measurementLabel } from "@/lib/measurement-labels";
import { bilingualLabel, savedComparison } from "@/lib/report-locale";
import { agentNextPractice, agentReflectionInterpretation, reportIntentReflection, type AgentReport } from "@/lib/agent-report";

function time(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const METRIC_EXPLANATIONS: Record<string, [string, string]> = {
  pitch_change: ["발화의 평균 음높이입니다. 핵심 문장의 높낮이를 주변 발화와 비교하세요.", "Average vocal pitch. Compare key sentences with the surrounding speech."],
  pitch_variability: ["발화 중 음높이의 변동 폭입니다. 강조 구간의 억양이 명확하게 구분되는지 확인하세요.", "Pitch variation during speech. Review whether the intended emphasis is distinct."],
  lip_tension: ["입의 높이와 너비를 비교한 비율입니다. 해당 장면의 입 움직임과 발음의 명료도를 함께 확인하세요.", "Mouth height relative to width. Review mouth movement alongside speech clarity in the recording."],
  brow_tension: ["눈썹이 아래로 움직인 정도입니다. 표정과 메시지의 전달 의도가 일치하는지 검토하세요.", "Degree of brow lowering. Review whether the expression matches the intended message."],
  gaze: ["카메라 기준 시선 위치의 안정도입니다. 핵심 문장 발화 시 시선이 향한 위치를 확인하세요.", "Gaze-position stability relative to the camera. Review gaze direction during key sentences."],
  v2_mean_f0: ["발화의 평균 음높이입니다. 핵심 문장의 높낮이를 주변 발화와 비교하세요.", "Average vocal pitch. Compare key sentences with the surrounding speech."],
  v2_jitter: ["짧은 음성 주기 사이의 높낮이 변동입니다. 동일 문장을 재생해 발성의 흐름을 비교하세요.", "Pitch variation between short voice cycles. Replay the same sentence to compare vocal delivery."],
  v2_shimmer: ["짧은 음성 주기 사이의 크기 변동입니다. 동일 문장을 재생해 발성의 흐름을 비교하세요.", "Amplitude variation between short voice cycles. Replay the same sentence to compare vocal delivery."],
  v2_hnr: ["규칙적인 음성 성분과 잡음 성분의 비율입니다. 수치와 함께 해당 구간의 음성을 검토하세요.", "Ratio of regular voice harmonics to noise. Review the measurement alongside the recorded speech."],
  v2_brow_down: ["눈썹이 아래로 움직인 정도입니다. 표정과 메시지의 전달 의도가 일치하는지 검토하세요.", "Degree of brow lowering. Review whether the expression matches the intended message."],
  v2_eye_squint: ["눈꺼풀이 좁아지는 움직임의 정도입니다. 해당 시점의 눈 주변 움직임을 확인하세요.", "Degree of eyelid tightening. Review the eye-area movement at that moment."],
  v2_jaw_open: ["턱이 벌어지는 움직임의 정도입니다. 영상과 음성을 함께 재생해 문장 사이의 쉼을 확인하세요.", "Degree of jaw opening. Review the recording with sound to assess pauses between sentences."],
};

function fixedUnit(value: number, unit: string): string {
  return `${value.toFixed(2)}${unit ? ` ${unit}` : ""}`;
}

export function conceptBarPercent(value: number): number {
  return Math.max(0, Math.min(1, value)) * 100;
}

export function AgentObservationReport({ report, ko, onAnswer, canReviewVideo = false, showModelOutputs = true }: {
  report: AgentReport; ko: boolean;
  showModelOutputs?: boolean;
  canReviewVideo?: boolean;
  onAnswer?: (answer: "intentional" | "unintentional" | "unsure") => void;
}) {
  const observed = report.observationReport;
  if (!observed) return null; // Reports saved before this schema have only summaryText.
  const previous = observed.previousComparison;
  const phases = observed.phaseSummaries ?? [];
  const phaseLabels = ko ? ["도입", "중반", "마무리"] : ["Opening", "Middle", "Closing"];
  const first = phases[0]?.averageStressScore;
  const last = phases[2]?.averageStressScore;
  const comparablePhases = phases.length === 3 && phases[0].observedMs >= (phases[0].endMs - phases[0].startMs) / 2
    && phases[2].observedMs >= (phases[2].endMs - phases[2].startMs) / 2;
  const baseline = observed.personalBaseline;
  const reflection = canReviewVideo ? reportIntentReflection(report) : undefined;
  const practice = reflection?.answer ? agentNextPractice(report, ko) : "";
  const answerLabels = ko
    ? { intentional: "네, 의도했어요", unintentional: "아니요", unsure: "잘 모르겠어요" }
    : { intentional: "Yes, intentional", unintentional: "No", unsure: "I'm not sure" };
  const signedPoints = (value: number | null) => value === null ? "—" : `${Math.round(value * 100) > 0 ? "+" : ""}${Math.round(value * 100)}${ko ? "점" : " points"}`;
  return <div className="coach-stack">
    {baseline && <div className="coach-card coach-data">
      <h3>{ko ? "개인 기준선과 비교" : "Compared with your personal baseline"}</h3>
      <p>{ko ? `준비 단계의 독립된 유효 분석 창 ${baseline.sampleCount}개 중앙값: ${Math.round(baseline.score * 100)}/100` :
        `Median of ${baseline.sampleCount} separate valid preparation windows: ${Math.round(baseline.score * 100)}/100`}</p>
      <p>{ko ? `발표 평균 차이 ${signedPoints(baseline.averageDifference)} · 최고 구간 차이 ${signedPoints(baseline.peakDifference)}` :
        `Session mean difference ${signedPoints(baseline.averageDifference)} · peak difference ${signedPoints(baseline.peakDifference)}`}</p>
      <small>{ko ? "준비 단계와 발표 중의 스트레스 신호를 비교합니다." : "Compare the stress signal during preparation with this presentation."}</small>
    </div>}
    {reflection && <div className="coach-card coach-data">
      <h3>{ko ? "전달 의도 확인" : "Delivery intent review"}</h3>
      <p>{ko
        ? `${time(reflection.startMs)}–${time(reflection.endMs)} 구간의 음높이 변화는 의도한 강조였나요?`
        : `Was the pitch change at ${time(reflection.startMs)}–${time(reflection.endMs)} an intentional emphasis?`}</p>
      <div className="agent-reflection-options">{(["intentional", "unintentional", "unsure"] as const).map((answer) =>
        <button key={answer} type="button" className={reflection.answer === answer ? "btn btn-primary" : "btn btn-outline"}
          aria-pressed={reflection.answer === answer} disabled={!onAnswer} onClick={() => onAnswer?.(answer)}>{answerLabels[answer]}</button>)}</div>
      {reflection.answer && <p>{ko ? "코치: " : "Coach: "}{agentReflectionInterpretation(report, ko)}</p>}
    </div>}
    {phases.some((item) => item.averageStressScore !== null) && <div className="coach-card coach-data">
      <h3>{ko ? "발표 흐름" : "How the session changed"}</h3>
      <p>{ko ? "도입부터 마무리까지 스트레스 신호가 어떻게 달라졌는지 살펴보세요." : "Follow how the stress signal changed from opening to closing."}</p>
      <div className="observation-phase-grid">{phases.map((item, index) => <div key={index}>
        <strong>{phaseLabels[index]}</strong><span>{item.averageStressScore === null ? "—" : `${Math.round(item.averageStressScore * 100)}/100`}</span>
        <small>{time(item.startMs)}–{time(item.endMs)} · {ko ? "분석" : "observed"} {Math.round(item.observedMs / 1000)}{ko ? "초" : "s"}</small>
      </div>)}</div>
      {comparablePhases && first !== null && first !== undefined && last !== null && last !== undefined && <p>{Math.round((last - first) * 100) === 0
        ? (ko ? "도입과 마무리의 평균 스트레스 신호는 거의 같았습니다. 두 구간의 실제 발화를 함께 비교해 보세요." : "Opening and closing had nearly the same mean stress signal score. Compare the recorded speech in both intervals.")
        : ko ? `마무리 구간의 평균 스트레스 신호는 도입보다 ${Math.abs(Math.round((last - first) * 100))}점 ${last > first ? "높았습니다" : "낮았습니다"}. 각 구간의 실제 발화와 함께 비교해 보세요.`
          : `The closing interval's mean stress signal score was ${Math.abs(Math.round((last - first) * 100))} points ${last > first ? "higher" : "lower"} than the opening interval. Compare this with the recording.`}</p>}
    </div>}
    {showModelOutputs && <AgentModelOutputs report={report} ko={ko} />}
    <div className="coach-card coach-data">
      <h3>{ko ? "영상에서 확인할 변화" : "Changes to review in the recording"}</h3>
      {(observed.patterns ?? []).length > 0 ? (observed.patterns ?? []).map((item) => <p key={item.id}>
        <strong>{time(item.startMs)}–{time(item.endMs)} · {bilingualLabel(item.label, ko, measurementLabel(item.id, ko))}</strong><br />
        {ko ? `해당 구간 ${item.value.toFixed(2)}${item.unit ? ` ${item.unit}` : ""} · 다른 분석 창 중앙값 ${item.comparisonValue.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}` :
          `This interval ${item.value.toFixed(2)}${item.unit ? ` ${item.unit}` : ""} · median of other windows ${item.comparisonValue.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}`}
      </p>) : <p>{observed.features.length === 0
        ? (ko ? "비교할 음성·영상 측정값이 수집되지 않았습니다." : "No audio or video features were available for comparison.")
        : (ko ? "구간별 음성·영상 특징의 차이가 뚜렷하지 않았습니다." : "Audio and video features showed no clear interval difference.")}</p>}
      {previous && <p>{ko ? `이전 저장 기록 ${previous.previousSessionCount ?? 1}건과 비교: ${previous.label.split(" / ")[0]} 중앙값 ${previous.previousValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""} → 이번 ${previous.currentValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""}` :
        `Compared with ${previous.previousSessionCount ?? 1} saved session(s): ${previous.label.split(" / ")[1] || previous.label} ${previous.previousValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""} → ${previous.currentValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""}`}</p>}
      {(observed.peakConcepts ?? []).length > 0 && <p>{ko ? "같은 구간의 패턴 변화: " : "Patterns in that interval: "}{(observed.peakConcepts ?? []).map((item) => `${measurementLabel(item.name, ko)} ${item.value.toFixed(2)} (${ko ? "다른 창 중앙값" : "other-window median"} ${item.comparisonValue.toFixed(2)})`).join(" · ")}</p>}
      <AgentEvidence report={report} ids={report.observationEvidenceIds} ko={ko} />
    </div>
    {practice && <div className="coach-card coach-ok"><h3>{ko ? "권장 연습" : "Recommended practice"}</h3><p>{practice}</p></div>}
  </div>;
}

export function AgentPatternReview({ report, ko, onSeek }: {
  report: AgentReport;
  ko: boolean;
  onSeek?: (ms: number) => void;
}) {
  const pattern = savedComparison(report);
  if (!pattern) return null;

  const interval = `${time(pattern.startMs)}–${time(pattern.endMs)}`;
  const narrowerPitch = pattern.id === "pitch_variability" && pattern.value < pattern.comparisonValue;
  const interpretation = narrowerPitch
    ? (ko
      ? "이 구간을 한 번 듣고, 청중이 기억했으면 하는 문장 하나를 고르세요. 그 문장이 앞뒤 문장 사이에서 바로 구분되어 들리는지 확인하세요."
      : "Listen once and pick the sentence you want the audience to remember. Check whether it stands out from the sentences around it.")
    : METRIC_EXPLANATIONS[pattern.id]?.[ko ? 0 : 1];
  return <section className="review-section">
    <div className="review-section-heading">
      <h3>{ko ? "구간별 관찰" : "Interval observation"}</h3>
      <button type="button" className="review-time-link" disabled={!onSeek} onClick={() => onSeek?.(pattern.startMs)}>{interval}</button>
    </div>
    <div className="review-finding-action">
      <div>
        <strong>{measurementLabel(pattern.id, ko)}</strong>
        <p>{fixedUnit(pattern.value, pattern.unit)} · {ko ? "다른 구간 기준값" : "Reference from other intervals"} {fixedUnit(pattern.comparisonValue, pattern.unit)}</p>
      </div>
      {onSeek && interpretation && <div>
        <strong>{ko ? "듣고 확인할 점" : "What to listen for"}</strong>
        <p>{interpretation}</p>
      </div>}
      {onSeek && narrowerPitch && <div className="review-pattern-practice">
        <strong>{ko ? "핵심 문장이 묻혀 들린다면" : "If the key sentence blends in"}</strong>
        <p>{ko
          ? "같은 구간을 다시 말하되 핵심 문장 직전에 한 박자 쉬세요. 두 녹음을 번갈아 듣고 어느 쪽에서 핵심 문장이 더 또렷하게 구분되는지 비교하세요. 처음부터 잘 구분됐다면 현재 전달 방식을 유지하세요."
          : "Record the same passage again, pausing for one beat before the key sentence. Listen to both versions and compare which makes the key sentence easier to pick out. If it already stands out, keep your original delivery."}</p>
      </div>}
    </div>
  </section>;
}

export function AgentModelOutputs({ report, ko }: { report: AgentReport; ko: boolean }) {
  const observed = report.observationReport;
  if (!observed || (!observed.concepts.length && !observed.features.length)) return null;
  const isAudio=(id:string)=>id.startsWith("pitch_") || ["v2_mean_f0","v2_jitter","v2_shimmer","v2_hnr"].includes(id);
  const featureGroups = [
    { label: ko ? "음성 특성 · 측정 지표" : "Vocal characteristics · measurements", items: observed.features.filter((item) => isAudio(item.id)) },
    { label: ko ? "표정·시선 특성 · 측정 지표" : "Expression and gaze · measurements", items: observed.features.filter((item) => !isAudio(item.id)) },
  ];
  return <section className="review-section review-model-outputs" aria-label={ko ? "음성·비언어 특성 분석" : "Vocal and nonverbal analysis"}>
      <div className="review-section-heading"><h3>{ko ? "음성·비언어 특성 분석" : "Vocal and nonverbal analysis"}</h3><span className="review-scale">{ko ? "전체 세션" : "Full session"}</span></div>
      {observed.concepts.length > 0 && <div className="observation-section">
        <strong>{ko ? "발표 특성 · 추정 지표" : "Presentation characteristics · estimates"}</strong>
        <div className="observation-scale"><span>0</span><span>1</span></div>
        <div className="observation-bars">{observed.concepts.map((item) => <div className="observation-bar-row" key={item.name}>
          <span>{measurementLabel(item.name, ko)}</span><div className="observation-bar-track" role="progressbar" aria-label={measurementLabel(item.name, ko)} aria-valuemin={0} aria-valuemax={1} aria-valuenow={conceptBarPercent(item.meanValue) / 100}><div className="observation-bar-fill" style={{ width: `${conceptBarPercent(item.meanValue)}%` }} /></div><b className={item.meanValue > 1 ? "observation-value-over-range" : undefined}>{item.meanValue.toFixed(2)}</b>
        </div>)}</div>
        {observed.concepts.some((item) => item.meanValue < 0 || item.meanValue > 1) && <p>{ko ? "표시 범위를 벗어난 값은 오른쪽 수치를 참고하세요." : "Values beyond the bar range are shown in the number on the right."}</p>}
      </div>}
      {featureGroups.map((group) => group.items.length > 0 && <div className="observation-section" key={group.label}>
        <strong>{group.label}</strong>
        <div className="observation-table-wrap"><table className="observation-table"><thead><tr><th>{ko ? "측정 항목" : "Measurement"}</th><th>{ko ? "평균" : "Mean"}</th><th>{ko ? "관측 범위" : "Observed range"}</th><th>{ko ? "해석 및 확인 사항" : "Interpretation and review"}</th></tr></thead><tbody>
          {group.items.map((item) => <tr key={item.id}><td>{measurementLabel(item.id, ko)}</td><td>{fixedUnit(item.meanValue, item.unit)}</td><td>{fixedUnit(item.minValue, item.unit)}–{fixedUnit(item.maxValue, item.unit)}</td><td>{METRIC_EXPLANATIONS[item.id]?.[ko ? 0 : 1] ?? ""}</td></tr>)}
        </tbody></table></div>
      </div>)}
  </section>;
}

export function AgentEvidence({ report, ids, ko }: { report: AgentReport; ids?: string[]; ko: boolean }) {
  const sources = (report.evidence ?? []).filter((item) => ids?.includes(item.id));
  if (!sources.length) return null;
  return <div className="signal-note"><strong>{ko ? "참고한 논문" : "Papers consulted"}</strong>{sources.map((item) => {
    const url = item.articleUrl || (item.doi ? `https://doi.org/${item.doi}` : null);
    const label = item.title || item.source;
    return <p key={item.id}>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{label}</a> : label}{item.page ? ` · p.${item.page}` : ""}{item.applicability === "related" ? (ko ? " · 관련 배경" : " · related context") : ""}{ko && item.findingKo ? ` · ${item.findingKo}` : ""}</p>;
  })}</div>;
}
