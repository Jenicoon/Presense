import type { AgentReport } from "@/lib/agent-report";

type Finding = AgentReport["priorities"][number];
type Observation = NonNullable<Finding["observations"]>[number];
const metricFloors: Record<string, number> = {f0_mean: 100, f0_std: 20, egemap_f0_semitone: 10, egemap_jitter: .01, egemap_shimmer_db: .2, egemap_hnr_db: 1};

/** Same conservative consistency rule as the server, not a presentation grade. */
export function repeatedGroupReason(rows: Observation[], reference: number | null | undefined, metric: string): string | null {
  if (typeof reference !== "number" || !Number.isFinite(reference)) return "missing_reference";
  if (rows.length < 2) return "insufficient_independent_observations";
  const ordered = [...rows].sort((a,b) => a.startMs-b.startMs || a.endMs-b.endMs);
  if (ordered.some((row,i) => i > 0 && ordered[i-1].endMs > row.startMs)) return "overlapping_observations";
  const values = rows.map(row=>row.value);
  if (values.some(value=>typeof value !== "number" || !Number.isFinite(value))) return "missing_measurement";
  const changes = values.map(value=>value-reference);
  if (changes.some(value=>Math.abs(value)<Math.max(Math.abs(reference),metricFloors[metric] ?? .15)*.1)) return "includes_reference_like_observation";
  if (!(changes.every(value=>value>0) || changes.every(value=>value<0))) return "mixed_directions";
  if (Math.max(...values)-Math.min(...values)>=Math.min(...changes.map(Math.abs))) return "dissimilar_changes";
  return null;
}
function independent<T extends {startMs:number;endMs:number}>(rows:T[]):T[] {
  const result:T[]=[];
  for (const row of [...rows].sort((a,b)=>a.endMs-b.endMs || a.startMs-b.startMs))
    if (!result.length || row.startMs>=result[result.length-1].endMs) result.push(row);
  return result;
}
function median(values:number[]) {
  const sorted=[...values].sort((a,b)=>a-b), n=sorted.length;
  return n%2 ? sorted[Math.floor(n/2)] : (sorted[n/2-1]+sorted[n/2])/2;
}
/** Rebuild exact selected evidence; unsupported saved findings become references. */
export function completeReportEvidence(report: AgentReport): AgentReport {
  if (!Array.isArray(report.priorities)) return report;
  const raw = new Map((report.rawSegments ?? []).map(row => [row.segmentId, row]));
  const priorities:Finding[]=[], references:Finding[]=[];
  const findings=[...report.priorities,...(report.referenceFindings ?? [])];
  for (const finding of findings.filter((f,i)=>findings.findIndex(other=>other.id===f.id)===i)) {
    const {modality,metric}=finding;
    const action=[...(report.agentRun?.actions ?? [])].reverse().find(row=>row.action==="analyze_segment" && row.candidateId===finding.id && row.segmentIds?.length);
    const ids=finding.selectedSegmentIds ?? action?.segmentIds ?? finding.observations?.map(row=>row.segmentId) ?? [];
    const valueFor=(row:NonNullable<AgentReport["rawSegments"]>[number])=>{
      const valid=modality==="audio" ? row.quality.audioValid : modality==="video" ? row.quality.faceDetected : modality==="concept" && row.quality.audioValid && row.quality.faceDetected;
      const values=modality==="audio" ? row.audioFeatures : modality==="video" ? row.videoFeatures : row.concepts;
      const value=metric ? values[metric] : undefined;
      return valid && typeof value==="number" && Number.isFinite(value) && !(metric==="f0_mean" && value<=0) && !(metric==="f0_std" && value<0) ? value : null;
    };
    const selected=[...new Set(ids)].flatMap(id=>{
      const row=raw.get(id), value=row ? valueFor(row) : null;
      return row && value!==null ? [{segmentId:row.segmentId,startMs:row.startMs,endMs:row.endMs,value,stressScore:row.stressScore,conceptValues:row.quality.audioValid && row.quality.faceDetected ? row.concepts : {}}] : [];
    });
    const restored=independent(selected);
    const earliest=Math.min(...selected.map(row=>row.startMs));
    const earlier=independent([...raw.values()].filter(row=>row.endMs<=earliest && valueFor(row)!==null));
    const reference=earlier.length>=2 ? median(earlier.map(row=>valueFor(row)!)) : null;
    const reason=!modality || !metric || !raw.size ? "missing_original_evidence" : repeatedGroupReason(restored,reference,metric);
    const recordedObservationCount=finding.recordedObservationCount ?? finding.independentObservations ?? restored.length;
    const updated={...finding,recordedObservationCount,groupingStatus:reason===null ? "verified" as const : "reference_only" as const,groupingReason:reason};
    if (reason===null) {
      priorities.push({...updated,selectedSegmentIds:[...new Set(ids)],referenceValue:reference,observations:restored,independentObservations:restored.length,verifiedObservationCount:restored.length,observationEvidenceComplete:restored.length===recordedObservationCount});
    } else {
      // Preserve every available reference, including overlap; never call it repetition.
      const observations=(raw.size && modality && metric ? selected : finding.observations ?? []).filter(row=>Number.isFinite(row.startMs) && Number.isFinite(row.endMs) && row.startMs>=0 && row.endMs>row.startMs && Number.isFinite(row.value)).sort((a,b)=>a.startMs-b.startMs || a.endMs-b.endMs);
      references.push({...updated,observations,verifiedObservationCount:restored.length,observationEvidenceComplete:false});
    }
  }
  return {...report,priorities,referenceFindings:references};
}
