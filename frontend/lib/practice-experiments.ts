import methods from "../../shared/practice-experiments.json";
import guidance from "../../shared/concept-v2-guidance.json";
import type { AgentReport } from "@/lib/agent-report";

export type PracticeMethodId = keyof typeof methods;
export type PracticeInstructions = { reason: string; goal: string; steps: string[]; question: string };
export function practiceMethods(findingId: string): PracticeMethodId[] {
  const v2 = (guidance as Record<string, { strategies: string[] }>)[findingId];
  const legacy: Record<string, string[]> = {
    pitch_change: ["contrast", "phrasing", "two_versions"], pitch_variability: ["contrast", "phrasing", "two_versions"],
    lip_tension: ["clear_phrases", "two_versions"], brow_tension: ["expression"], gaze: ["gaze_anchor"],
  };
  return (v2?.strategies ?? legacy[findingId] ?? ["phrasing"]).filter(id => Object.hasOwn(methods, id)) as PracticeMethodId[];
}
export function practiceMethod(id: PracticeMethodId, ko: boolean) {
  const source = methods[id]; const language = ko ? 0 : 1;
  return { label: source.label[language], goal: source.goal[language], steps: source.steps.map(step => step[language]), question: source.question[language] };
}
export function verifiedPracticePlan(report: AgentReport, finding: AgentReport["priorities"][number]) {
  const plan = finding.practicePlan;
  if (report.synthesisStatus !== "generated" || finding.evidenceStatus !== "cited_excerpt" || !plan
    || plan.kind !== "comparison_experiment" || plan.source !== "ai_selected" || plan.definitionVersion !== "comparison-experiments-v1"
    || !practiceMethods(finding.id).includes(plan.strategyId as PracticeMethodId)) return null;
  if (!plan.instructions || !plan.language || plan.language !== report.language
    || !plan.instructions.reason?.trim() || !plan.instructions.goal?.trim() || !plan.instructions.question?.trim()
    || !Array.isArray(plan.instructions.steps) || plan.instructions.steps.length < 2 || plan.instructions.steps.length > 4
    || plan.instructions.steps.some(step => typeof step !== "string" || !step.trim())) return null;
  if (!finding.evidenceIds?.some(id => report.evidence?.some(source => source.id === id))) return null;
  const target = finding.observations?.find(row => row.segmentId === plan.segmentId && row.startMs === plan.startMs && row.endMs === plan.endMs);
  return target ? { ...plan, strategyId: plan.strategyId as PracticeMethodId } : null;
}
