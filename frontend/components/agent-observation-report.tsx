import v2Guidance from "../../shared/concept-v2-guidance.json";
import { measurementLabel } from "@/lib/measurement-labels";
import { bilingualLabel } from "@/lib/report-locale";
import { agentNextPractice, type AgentReport } from "@/lib/agent-report";

function time(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

const METRIC_EXPLANATIONS: Record<string, [string, string]> = {
  pitch_change: ["목소리의 평균 높이입니다. 높거나 낮은 쪽이 더 좋은 것은 아니며 평소 목소리·전달 의도와 비교하세요.", "Average voice pitch. Higher or lower is not inherently better; compare with your usual voice and intended delivery."],
  pitch_variability: ["한 분석 창 안에서 목소리 높이가 변한 정도입니다. 낮으면 비교적 일정하고 높으면 변화가 큽니다. 강조하려던 대목과 함께 들어보세요.", "Variation of voice pitch within a window. Lower means steadier; higher means more variation. Listen alongside the intended emphasis."],
  lip_tension: ["실제로는 입 높이/너비 비율입니다. 낮으면 입 벌림이 작고 높으면 큽니다. 발음의 좋고 나쁨을 이 값만으로 정하지 않습니다.", "This is a mouth height-to-width ratio. Lower means less opening; higher means more. It does not rate articulation by itself."],
  brow_tension: ["눈썹 내림 움직임의 카메라 추정치입니다. 높으면 움직임이 더 크게 잡힌 것이며, 표정의 좋고 나쁨은 영상 맥락에서 확인하세요.", "A camera estimate of brow lowering. Higher means more detected movement; judge the expression in the recording's context."],
  gaze: ["화면에서 홍채 위치가 얼마나 안정적인지의 추정치입니다. 높으면 카메라 기준으로 더 안정적이지만 실제 청중과의 눈맞춤 점수는 아닙니다.", "A camera estimate of iris-position stability. Higher means steadier relative to the camera, not necessarily better audience eye contact."],
};

function fixedUnit(value: number, unit: string): string {
  return `${value.toFixed(2)}${unit ? ` ${unit}` : ""}`;
}

export function conceptBarPercent(value: number): number {
  return Math.max(0, Math.min(1, value)) * 100;
}

export function AgentObservationReport({ report, ko }: { report: AgentReport; ko: boolean }) {
  const observed = report.observationReport;
  if (!observed) return null; // Reports saved before this schema have only summaryText.
  const isAudio=(id:string)=>id.startsWith("pitch_") || ["v2_mean_f0","v2_jitter","v2_shimmer","v2_hnr"].includes(id);
  const featureGroups = [
    { label: ko ? "음성" : "Audio", items: observed.features.filter((item) => isAudio(item.id)) },
    { label: ko ? "영상" : "Video", items: observed.features.filter((item) => !isAudio(item.id)) },
  ];
  const previous = observed.previousComparison;
  const phases = observed.phaseSummaries ?? [];
  const phaseLabels = ko ? ["도입", "중반", "마무리"] : ["Opening", "Middle", "Closing"];
  const first = phases[0]?.averageStressScore;
  const last = phases[2]?.averageStressScore;
  const comparablePhases = phases.length === 3 && phases[0].observedMs >= (phases[0].endMs - phases[0].startMs) / 2
    && phases[2].observedMs >= (phases[2].endMs - phases[2].startMs) / 2;
  return <div className="coach-stack">
    {phases.some((item) => item.averageStressScore !== null) && <div className="coach-card coach-data">
      <h3>{ko ? "발표 흐름" : "How the session changed"}</h3>
      <p>{ko ? "숫자가 낮으면 해당 구간을 모델이 스트레스 쪽으로 분류한 정도가 낮다는 뜻입니다. 전달이 좋았는지는 영상과 함께 확인하세요." : "A lower number means the model leaned less toward its stress class in that interval. Review the recording to judge delivery."}</p>
      <div className="observation-phase-grid">{phases.map((item, index) => <div key={index}>
        <strong>{phaseLabels[index]}</strong><span>{item.averageStressScore === null ? "—" : `${Math.round(item.averageStressScore * 100)}/100`}</span>
        <small>{time(item.startMs)}–{time(item.endMs)} · {ko ? "분석" : "observed"} {Math.round(item.observedMs / 1000)}{ko ? "초" : "s"}</small>
      </div>)}</div>
      {comparablePhases && first !== null && first !== undefined && last !== null && last !== undefined && <p>{Math.round((last - first) * 100) === 0
        ? (ko ? "도입과 마무리의 평균 스트레스 신호는 거의 같았습니다. 두 구간의 실제 발화를 함께 비교해 보세요." : "Opening and closing had nearly the same mean stress signal score. Compare the recorded speech in both intervals.")
        : ko ? `마무리 구간의 평균 스트레스 신호는 도입보다 ${Math.abs(Math.round((last - first) * 100))}점 ${last > first ? "높았습니다" : "낮았습니다"}. 각 구간의 실제 발화와 함께 비교해 보세요.`
          : `The closing interval's mean stress signal score was ${Math.abs(Math.round((last - first) * 100))} points ${last > first ? "higher" : "lower"} than the opening interval. Compare this with the recording.`}</p>}
    </div>}
    {(observed.concepts.length > 0 || observed.features.length > 0) && <div className="coach-card coach-data">
      <h3>{ko ? "관찰된 모델 출력" : "Observed model outputs"}</h3>
      {observed.modelWindowCount !== undefined && <p>{ko ? `모델 분석 창 ${observed.modelWindowCount}개 · 각 창은 최대 10초이며 서로 겹칠 수 있습니다.` : `${observed.modelWindowCount} model analysis windows · each covers up to 10 seconds and may overlap.`}</p>}
      {observed.concepts.length > 0 && <div className="observation-section">
        <strong>{ko ? "모델이 예측한 특징" : "Model-predicted features"}</strong>
        <p>{ko ? "막대는 학습 자료의 기준으로 환산한 예측값이며, 아래의 실제 측정값과 구분해서 보세요. 스트레스의 원인이나 발표의 좋고 나쁨을 뜻하지 않습니다." : "Bars show predictions relative to the training reference, separately from actual measurements below. They do not identify causes of stress or grade delivery."}</p>
        <div className="observation-scale"><span>0</span><span>1</span></div>
        <div className="observation-bars">{observed.concepts.map((item) => <div className="observation-bar-row" key={item.name}>
          <span>{measurementLabel(item.name, ko)}</span><div className="observation-bar-track" role="progressbar" aria-label={measurementLabel(item.name, ko)} aria-valuemin={0} aria-valuemax={1} aria-valuenow={conceptBarPercent(item.meanValue) / 100}><div className="observation-bar-fill" style={{ width: `${conceptBarPercent(item.meanValue)}%` }} /></div><b className={item.meanValue > 1 ? "observation-value-over-range" : undefined}>{item.meanValue.toFixed(2)}</b>
        </div>)}</div>
        {observed.concepts.some((item) => item.meanValue < 0 || item.meanValue > 1) && <p>{ko ? "0 미만·1 초과 출력은 막대 끝에 맞춰 표시하고, 오른쪽 숫자는 원래 값을 유지합니다." : "Outputs outside 0–1 are clipped on the bar; the number retains the original value."}</p>}
      </div>}
      {featureGroups.map((group) => group.items.length > 0 && <div className="observation-section" key={group.label}>
        <strong>{group.label}</strong>
        <div className="observation-table-wrap"><table className="observation-table"><thead><tr><th>{ko ? "측정 항목" : "Measurement"}</th><th>{ko ? "평균" : "Mean"}</th><th>{ko ? "관측 범위" : "Observed range"}</th><th>{ko ? "어떻게 읽나요?" : "How to read it"}</th></tr></thead><tbody>
          {group.items.map((item) => <tr key={item.id}><td>{bilingualLabel(item.label, ko, measurementLabel(item.id, ko))}</td><td>{fixedUnit(item.meanValue, item.unit)}</td><td>{fixedUnit(item.minValue, item.unit)}–{fixedUnit(item.maxValue, item.unit)}</td><td>{METRIC_EXPLANATIONS[item.id]?.[ko ? 0 : 1] ?? (v2Guidance as Record<string,{check:string[]}>)[item.id]?.check[ko ? 0 : 1] ?? ""}</td></tr>)}
        </tbody></table></div>
      </div>)}
    </div>}
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
      {(observed.peakConcepts ?? []).length > 0 && <p>{ko ? "같은 구간의 패턴 변화: " : "Concept outputs in that interval: "}{(observed.peakConcepts ?? []).map((item) => `${measurementLabel(item.name, ko)} ${item.value.toFixed(2)} (${ko ? "다른 창 중앙값" : "other-window median"} ${item.comparisonValue.toFixed(2)})`).join(" · ")}</p>}
      <AgentEvidence report={report} ids={report.observationEvidenceIds} ko={ko} />
    </div>
    <div className="coach-card coach-ok"><h3>{ko ? "이번 연습에서 해볼 것" : "Focus for the next take"}</h3><p>{agentNextPractice(report, ko)}</p></div>
  </div>;
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
