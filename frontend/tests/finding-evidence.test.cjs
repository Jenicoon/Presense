const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const exportsForTest = {};
new Function('exports', ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/finding-evidence.ts'),'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(exportsForTest);
const {completeReportEvidence} = exportsForTest;
function legacy() {
  const rawSegments = Array.from({length:6}, (_, n)=>({segmentId:`s${n}`,startMs:n*10000,endMs:(n+1)*10000,stressScore:.2+n*.1,concepts:{},audioFeatures:{f0_std:n<2 ? 20+n : 40+n},videoFeatures:{},quality:{audioValid:true,faceDetected:true}}));
  return {sessionId:'four',rawSegments,priorities:[{id:'pitch_variability',modality:'audio',metric:'f0_std',independentObservations:4,ranges:[{startMs:20000,endMs:60000}],observations:rawSegments.slice(2,5).map(s=>({...s,value:s.audioFeatures.f0_std}))}],agentRun:{actions:[{action:'analyze_segment',candidateId:'pitch_variability',segmentIds:['s2','s3','s4','s5']}]}};
}
test('all four saved selected intervals are available even when a legacy report stored three examples',()=>{
  const report=legacy(), original=structuredClone(report);
  const finding=completeReportEvidence(report).priorities[0];
  assert.deepEqual(finding.observations.map(o=>o.startMs),[20000,30000,40000,50000]);
  assert.equal(finding.observationEvidenceComplete,true);
  assert.equal(finding.verifiedObservationCount,4);
  assert.deepEqual(report,original);
});
test('a merged range never fills in an interval that was not selected',()=>{
  const report=legacy(); report.agentRun.actions[0].segmentIds=['s2','s4']; report.priorities[0].independentObservations=2;
  assert.deepEqual(completeReportEvidence(report).priorities[0].observations.map(o=>o.segmentId),['s2','s4']);
});
test('missing or poor quality original evidence is disclosed rather than invented',()=>{
  const report=legacy(); report.rawSegments[5].quality.audioValid=false;
  const finding=completeReportEvidence(report).priorities[0];
  assert.equal(finding.observationEvidenceComplete,false);
  assert.equal(finding.observations.length,3);
});

test('legacy example with overlap and mixed change stays as three individual references',()=>{
  const observations=[{segmentId:'a',startMs:57000,endMs:67000,value:.52},{segmentId:'b',startMs:68000,endMs:78000,value:.2},{segmentId:'c',startMs:75000,endMs:85000,value:.41}];
  const report={analysis:{durationMs:85000},priorities:[{id:'audio:energy_variability',referenceValue:.24,observations}]};
  const original=structuredClone(report), normalized=completeReportEvidence(report);
  assert.equal(normalized.priorities.length,0);
  assert.equal(normalized.referenceFindings[0].groupingReason,'missing_original_evidence');
  assert.deepEqual(normalized.referenceFindings[0].observations,observations);
  assert.deepEqual(report,original);
  assert.deepEqual(completeReportEvidence(normalized),normalized);
});
test('actual measurements overrule a saved claim of repeated change',()=>{
  const report=legacy();
  report.rawSegments[2].audioFeatures.f0_std=40;
  report.rawSegments[3].audioFeatures.f0_std=12;
  report.agentRun.actions[0].segmentIds=['s2','s3'];
  const normalized=completeReportEvidence(report);
  assert.equal(normalized.priorities.length,0);
  assert.equal(normalized.referenceFindings[0].groupingReason,'mixed_directions');
});
test('overlapping windows cannot count as two repeats',()=>{
  const report=legacy();
  report.rawSegments[3].startMs=25000;
  report.agentRun.actions[0].segmentIds=['s2','s3'];
  const normalized=completeReportEvidence(report);
  assert.equal(normalized.priorities.length,0);
  assert.equal(normalized.referenceFindings[0].observations.length,2);
});
test('grouping requires similar change direction and magnitude for every member',()=>{
  const {repeatedGroupReason}=exportsForTest;
  const rows=values=>values.map((value,n)=>({startMs:n*10000,endMs:(n+1)*10000,value}));
  assert.equal(repeatedGroupReason(rows([.52,.2,.41]),.24,'energy_variability'),'mixed_directions');
  assert.equal(repeatedGroupReason(rows([.52,.25]),.24,'energy_variability'),'includes_reference_like_observation');
  assert.equal(repeatedGroupReason(rows([.52,.28]),.24,'energy_variability'),'dissimilar_changes');
  assert.equal(repeatedGroupReason(rows([.52,.50]),.24,'energy_variability'),null);
  assert.equal(repeatedGroupReason(rows([.12,.10]),.24,'energy_variability'),null);
  assert.equal(repeatedGroupReason(rows([.52,.50]),null,'energy_variability'),'missing_reference');
});
