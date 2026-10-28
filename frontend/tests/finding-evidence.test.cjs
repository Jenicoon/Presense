const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const exportsForTest = {};
new Function('exports', ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/finding-evidence.ts'),'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(exportsForTest);
const {completeReportEvidence} = exportsForTest;
function legacy() {
  const rawSegments = Array.from({length:6}, (_, n)=>({segmentId:`s${n}`,startMs:n*10000,endMs:(n+1)*10000,stressScore:.2+n*.1,concepts:{},audioFeatures:{f0_std:20+n},videoFeatures:{},quality:{audioValid:true,faceDetected:true}}));
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
