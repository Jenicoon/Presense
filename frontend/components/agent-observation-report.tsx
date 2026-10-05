import { agentNextPractice, type AgentReport } from "@/lib/agent-report";

function time(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function AgentObservationReport({ report, ko }: { report: AgentReport; ko: boolean }) {
  const observed = report.observationReport;
  if (!observed) return null; // Reports saved before this schema have only summaryText.
  const peak = observed.peakSegment;
  const recommendation = report.priorities.find((item) => item.practiceSuggestion || item.reviewAction || item.recommendation);
  const nextPractice = agentNextPractice(report, ko);
  return <div className="coach-stack">
    <div className="coach-card coach-data">
      <h3>{ko ? "발표 요약 · 주요 구간" : "Session overview · key interval"}</h3>
      <p>{ko ? `분석 가능한 구간 ${Math.round(observed.observedMs / 1000)}초 (전체의 ${Math.round(observed.coverage * 100)}%)` :
        `${Math.round(observed.observedMs / 1000)} usable seconds (${Math.round(observed.coverage * 100)}% of session)`}</p>
      {observed.averageStressScore !== null && <p>{ko ? "평균 모델 스트레스 점수" : "Mean model stress score"}: {Math.round(observed.averageStressScore * 100)}/100</p>}
      {peak && <p>{ko ? "가장 높은 관측 구간" : "Highest observed interval"}: {time(peak.startMs)}–{time(peak.endMs)} · {Math.round(peak.stressScore * 100)}/100</p>}
    </div>
    {(observed.concepts.length > 0 || observed.features.length > 0) && <div className="coach-card coach-data">
      <h3>{ko ? "관찰된 모델 출력" : "Observed model outputs"}</h3>
      {observed.concepts.length > 0 && <p>{ko ? "Concept 출력 평균" : "Mean concept outputs"}: {observed.concepts.map((item) => `${item.name} ${item.meanValue.toFixed(2)}`).join(" · ")}</p>}
      {observed.features.map((item) => <p key={item.id}>{ko ? item.label.split(" / ")[0] : item.label.split(" / ")[1] || item.label}: {item.meanValue.toFixed(2)}{item.unit ? ` ${item.unit}` : ""} ({ko ? "관측" : "samples"} {item.observations})</p>)}
    </div>}
    <div className="coach-card coach-ok">
      <h3>{ko ? "개선점 · 다음 연습" : "Improvement focus · next practice"}</h3>
      {!recommendation && <p>{ko ? "현재 관측만으로 특정 음성·표정 특징을 개선점으로 확정할 근거가 부족합니다." : "The current observations do not establish a specific voice or facial feature to change."}</p>}
      <p>{nextPractice}</p>
    </div>
    <p className="signal-note">{ko ? "모델 점수와 Concept는 진단이나 원인 설명이 아닙니다. 가장 높은 구간은 이 발표 안에서의 상대적인 위치입니다." : "Model scores and concepts are not diagnoses or causes. The highest interval is relative to this session."}</p>
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
