import { agentNextPractice, type AgentReport } from "@/lib/agent-report";

function time(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function AgentObservationReport({ report, ko }: { report: AgentReport; ko: boolean }) {
  const observed = report.observationReport;
  if (!observed) return null; // Reports saved before this schema have only summaryText.
  const largestConcept = Math.max(...observed.concepts.map((item) => Math.abs(item.meanValue)), 0.01);
  const featureGroups = [
    { label: ko ? "음성" : "Audio", items: observed.features.filter((item) => item.id.startsWith("pitch_")) },
    { label: ko ? "영상" : "Video", items: observed.features.filter((item) => !item.id.startsWith("pitch_")) },
  ];
  const previous = observed.previousComparison;
  return <div className="coach-stack">
    {(observed.concepts.length > 0 || observed.features.length > 0) && <div className="coach-card coach-data">
      <h3>{ko ? "관찰된 모델 출력" : "Observed model outputs"}</h3>
      {observed.modelWindowCount !== undefined && <p>{ko ? `모델 분석 창 ${observed.modelWindowCount}개 · 각 창은 최대 10초이며 서로 겹칠 수 있습니다.` : `${observed.modelWindowCount} model analysis windows · each covers up to 10 seconds and may overlap.`}</p>}
      {observed.concepts.length > 0 && <div className="observation-section">
        <strong>{ko ? "Concept 출력" : "Concept outputs"}</strong>
        <div className="observation-bars">{observed.concepts.map((item) => <div className="observation-bar-row" key={item.name}>
          <span>{item.name}</span><div className="observation-bar-track"><div className="observation-bar-fill" style={{ width: `${Math.max(2, Math.abs(item.meanValue) / largestConcept * 100)}%` }} /></div><b>{item.meanValue.toFixed(2)}</b>
        </div>)}</div>
      </div>}
      {featureGroups.map((group) => group.items.length > 0 && <div className="observation-section" key={group.label}>
        <strong>{group.label}</strong>
        <div className="observation-table-wrap"><table className="observation-table"><thead><tr><th>{ko ? "측정 항목" : "Measurement"}</th><th>{ko ? "평균" : "Mean"}</th><th>{ko ? "관측 범위" : "Observed range"}</th></tr></thead><tbody>
          {group.items.map((item) => <tr key={item.id}><td>{ko ? item.label.split(" / ")[0] : item.label.split(" / ")[1] || item.label}</td><td>{item.meanValue.toFixed(2)}{item.unit ? ` ${item.unit}` : ""}</td><td>{item.minValue.toFixed(2)}–{item.maxValue.toFixed(2)}{item.unit ? ` ${item.unit}` : ""}</td></tr>)}
        </tbody></table></div>
      </div>)}
    </div>}
    <div className="coach-card coach-data">
      <h3>{ko ? "영상에서 확인할 변화" : "Changes to review in the recording"}</h3>
      {(observed.patterns ?? []).length > 0 ? (observed.patterns ?? []).map((item) => <p key={item.id}>
        <strong>{time(item.startMs)}–{time(item.endMs)} · {ko ? item.label.split(" / ")[0] : item.label.split(" / ")[1] || item.label}</strong><br />
        {ko ? `해당 구간 ${item.value.toFixed(2)}${item.unit ? ` ${item.unit}` : ""} · 다른 분석 창 중앙값 ${item.comparisonValue.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}` :
          `This interval ${item.value.toFixed(2)}${item.unit ? ` ${item.unit}` : ""} · median of other windows ${item.comparisonValue.toFixed(2)}${item.unit ? ` ${item.unit}` : ""}`}
      </p>) : <p>{observed.features.length === 0
        ? (ko ? "비교할 음성·영상 측정값이 수집되지 않았습니다." : "No audio or video features were available for comparison.")
        : (ko ? "구간별 음성·영상 특징의 차이가 뚜렷하지 않았습니다." : "Audio and video features showed no clear interval difference.")}</p>}
      {previous && <p>{ko ? `이전 저장 기록 ${previous.previousSessionCount ?? 1}건과 비교: ${previous.label.split(" / ")[0]} 중앙값 ${previous.previousValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""} → 이번 ${previous.currentValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""}` :
        `Compared with ${previous.previousSessionCount ?? 1} saved session(s): ${previous.label.split(" / ")[1] || previous.label} ${previous.previousValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""} → ${previous.currentValue.toFixed(2)}${previous.unit ? ` ${previous.unit}` : ""}`}</p>}
      <AgentEvidence report={report} ids={report.observationEvidenceIds} ko={ko} />
    </div>
    <div className="coach-card coach-ok"><h3>{ko ? "이번 연습에서 해볼 것" : "Focus for the next take"}</h3><p>{agentNextPractice(report, ko)}</p></div>
  </div>;
}

export function AgentEvidence({ report, ids, ko }: { report: AgentReport; ids?: string[]; ko: boolean }) {
  const sources = (report.evidence ?? []).filter((item) => ids?.includes(item.id));
  if (!sources.length) return null;
  return <div className="signal-note"><strong>{ko ? "관련 논문 근거" : "Related research"}</strong>{sources.map((item) => {
    const url = item.articleUrl || (item.doi ? `https://doi.org/${item.doi}` : null);
    const label = item.title || item.source;
    return <p key={item.id}>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{label}</a> : label}{ko && item.findingKo ? ` · ${item.findingKo}` : ""}</p>;
  })}</div>;
}
