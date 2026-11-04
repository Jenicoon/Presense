import { measurementLabel } from "@/lib/measurement-labels";
import { bilingualLabel } from "@/lib/report-locale";
import { agentNextPractice, agentReflectionInterpretation, type AgentReport } from "@/lib/agent-report";

function time(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const METRIC_EXPLANATIONS: Record<string, [string, string]> = {
  pitch_change: ["평균적인 목소리 높이예요. 중요한 문장이 주변보다 높거나 낮게 들리는지 들어보세요.", "Your average voice pitch. Listen for how key sentences rise or fall compared with the surrounding speech."],
  pitch_variability: ["목소리 높낮이가 바뀐 폭이에요. 강조한 문장과 나머지 문장을 비교해 보세요.", "How much your pitch varied. Compare the emphasized sentence with the rest of your speech."],
  lip_tension: ["입이 벌어진 정도예요. 소리와 함께 보며 단어가 또렷하게 들리는지 확인해 보세요.", "How open your mouth was. Watch with sound and listen for clear words."],
  brow_tension: ["눈썹이 아래로 움직인 정도예요. 전달하려던 느낌과 표정이 어울리는지 살펴보세요.", "How much your eyebrows moved downward. Review how the expression fits your intended tone."],
  gaze: ["시선 위치가 얼마나 일정했는지 보여줘요. 핵심 문장을 말할 때 어디를 보고 있었는지 살펴보세요.", "How steady your gaze position was. Check where you looked while saying the key sentence."],
  v2_mean_f0: ["평균적인 목소리 높이예요. 중요한 문장의 높낮이를 주변 문장과 비교해 보세요.", "Your average voice pitch. Compare the pitch of a key sentence with the surrounding speech."],
  v2_jitter: ["아주 짧은 소리 단위에서 높낮이가 달라진 정도예요. 같은 문장을 다시 들으며 목소리의 흐름을 비교해 보세요.", "Tiny pitch changes within the voice. Replay the same sentence and compare how it sounds."],
  v2_shimmer: ["아주 짧은 소리 단위에서 크기가 달라진 정도예요. 같은 문장을 다시 들으며 목소리의 흐름을 비교해 보세요.", "Tiny loudness changes within the voice. Replay the same sentence and compare how it sounds."],
  v2_hnr: ["목소리의 규칙적인 성분과 잡음 성분을 비교한 값이에요. 녹음에서 목소리가 어떻게 들리는지 함께 확인해 보세요.", "The balance of regular voice harmonics and noise. Listen to the recording alongside this measurement."],
  v2_brow_down: ["눈썹이 아래로 움직인 정도예요. 전달하려던 느낌과 표정이 어울리는지 살펴보세요.", "How much your eyebrows moved downward. Review how the expression fits your intended tone."],
  v2_eye_squint: ["눈꺼풀을 좁히는 움직임이에요. 눈을 가늘게 뜬 시점을 영상에서 살펴보세요.", "Movement that narrows the eyelids. Review those moments in the recording."],
  v2_jaw_open: ["턱을 여는 움직임이에요. 소리와 함께 보며 문장 사이의 쉼을 확인해 보세요.", "Jaw-opening movement. Watch with sound and listen for pauses between sentences."],
};

function fixedUnit(value: number, unit: string): string {
  return `${value.toFixed(2)}${unit ? ` ${unit}` : ""}`;
}

export function conceptBarPercent(value: number): number {
  return Math.max(0, Math.min(1, value)) * 100;
}

export function AgentObservationReport({ report, ko, onAnswer, showModelOutputs = true }: {
  report: AgentReport; ko: boolean;
  showModelOutputs?: boolean;
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
  const reflection = report.reflection;
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
      <small>{ko ? "준비할 때와 발표할 때의 스트레스 신호를 비교했어요." : "Compare the stress signal during preparation with this presentation."}</small>
    </div>}
    {reflection && <div className="coach-card coach-data">
      <h3>{ko ? "코치의 질문" : "Coach follow-up"}</h3>
      <p>{reflection.kind === "overall" ? (ko ? "이번 발표의 전달 방식이 의도한 대로였나요?" : "Did this presentation come across as you intended?") :
        ko ? `${time(reflection.startMs)}–${time(reflection.endMs)} 구간은 의도적으로 강조한 부분인가요?` :
        `Was ${time(reflection.startMs)}–${time(reflection.endMs)} an intentional emphasis?`}</p>
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
    <div className="coach-card coach-ok"><h3>{ko ? "이번 연습에서 해볼 것" : "Focus for the next take"}</h3><p>{agentNextPractice(report, ko)}</p></div>
  </div>;
}

export function AgentModelOutputs({ report, ko }: { report: AgentReport; ko: boolean }) {
  const observed = report.observationReport;
  if (!observed || (!observed.concepts.length && !observed.features.length)) return null;
  const isAudio=(id:string)=>id.startsWith("pitch_") || ["v2_mean_f0","v2_jitter","v2_shimmer","v2_hnr"].includes(id);
  const featureGroups = [
    { label: ko ? "목소리 · 측정값" : "Voice · measurements", items: observed.features.filter((item) => isAudio(item.id)) },
    { label: ko ? "표정·시선 · 측정값" : "Expression and gaze · measurements", items: observed.features.filter((item) => !isAudio(item.id)) },
  ];
  return <section className="review-section review-model-outputs" aria-label={ko ? "목소리와 표정" : "Voice and expression"}>
      <h3>{ko ? "목소리와 표정" : "Voice and expression"}</h3>
      {observed.concepts.length > 0 && <div className="observation-section">
        <strong>{ko ? "발표 특징 · 추정값" : "Presentation patterns · estimates"}</strong>
        <div className="observation-scale"><span>0</span><span>1</span></div>
        <div className="observation-bars">{observed.concepts.map((item) => <div className="observation-bar-row" key={item.name}>
          <span>{measurementLabel(item.name, ko)}</span><div className="observation-bar-track" role="progressbar" aria-label={measurementLabel(item.name, ko)} aria-valuemin={0} aria-valuemax={1} aria-valuenow={conceptBarPercent(item.meanValue) / 100}><div className="observation-bar-fill" style={{ width: `${conceptBarPercent(item.meanValue)}%` }} /></div><b className={item.meanValue > 1 ? "observation-value-over-range" : undefined}>{item.meanValue.toFixed(2)}</b>
        </div>)}</div>
        {observed.concepts.some((item) => item.meanValue < 0 || item.meanValue > 1) && <p>{ko ? "막대의 범위를 벗어난 값은 오른쪽 숫자로 확인할 수 있어요." : "Values beyond the bar range are shown in the number on the right."}</p>}
      </div>}
      {featureGroups.map((group) => group.items.length > 0 && <div className="observation-section" key={group.label}>
        <strong>{group.label}</strong>
        <div className="observation-table-wrap"><table className="observation-table"><thead><tr><th>{ko ? "측정 항목" : "Measurement"}</th><th>{ko ? "평균" : "Mean"}</th><th>{ko ? "관측 범위" : "Observed range"}</th><th>{ko ? "어떻게 읽나요?" : "How to read it"}</th></tr></thead><tbody>
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
