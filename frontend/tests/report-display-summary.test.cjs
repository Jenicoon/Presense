const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function loadTs(file) {
  const js = ts.transpileModule(fs.readFileSync(path.join(__dirname, file), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const exports = {};
  new Function('exports', 'require', js)(exports, (id) => {
    if (id.endsWith("concept-v2-guidance.json")) return {default:JSON.parse(fs.readFileSync(path.join(__dirname,"../../shared/concept-v2-guidance.json"),"utf8"))};
    if (id === '@/lib/measurement-labels') return loadTs('../lib/measurement-labels.ts');
    if (id === '@/lib/finding-evidence') return loadTs('../lib/finding-evidence.ts');
    if (id === '@/lib/report-locale') return loadTs('../lib/report-locale.ts');
    return {};
  });
  return exports;
}
const { reportDisplaySummary, agentNextPractice, reportIntentReflection } = loadTs('../lib/agent-report.ts');
const { findingText, sceneText } = loadTs('../lib/report-locale.ts');

test('older generic report uses its saved measurements in the displayed summary', () => {
  const report = {
    summaryText: '00:06–00:16 구간의 모델 스트레스 점수가 이번 발표에서 가장 높았습니다. 음성·영상 특징은 뚜렷한 구간 차이를 보이지 않았습니다.',
    observationReport: {
      averageStressScore: .52,
      peakSegment: { startMs: 6000, endMs: 16000, stressScore: .68 },
      phaseSummaries: [
        { startMs: 0, endMs: 10000, observedMs: 10000, averageStressScore: .4 },
        { startMs: 10000, endMs: 20000, observedMs: 10000, averageStressScore: .6 },
        { startMs: 20000, endMs: 30000, observedMs: 10000, averageStressScore: .5 },
      ],
      features: [{ id: 'pitch_change', label: '평균 목소리 높이 / Mean voice pitch', meanValue: 130, unit: 'Hz' }],
      concepts: [{ name: '음성 피치', meanValue: .7 }],
      peakConcepts: [],
    },
  };
  const summary = reportDisplaySummary(report, true);
  assert.match(summary, /00:06–00:16/);
  assert.match(summary, /68\/100/);
  assert.match(summary, /중반 평균 60\/100/);
  assert.match(summary, /평균 목소리 높이 130\.00 Hz/);
  assert.match(summary, /Concept 출력/);
});

test('specific generated report is retained verbatim', () => {
  const report = { summaryText: '구간별 관찰 내용입니다.' };
  assert.equal(reportDisplaySummary(report, true), report.summaryText);
});


test('a saved Korean finding is rendered from its actual measurements in English', () => {
  const finding = { id: 'pitch_change', metric: 'f0_mean', label: '평균 목소리 높이 / Mean voice pitch',
    observationText: '구간별 한국어 관찰입니다.', reviewAction: '한국어 영상 안내', practiceSuggestion: '한국어 연습 안내',
    referenceValue: 100, observations: [{ startMs: 25000, endMs: 35000, value: 200 }] };
  const translated = findingText(finding, false);
  assert.doesNotMatch(Object.values(translated).join(' '), /[가-힣]/);
  assert.match(translated.observation, /00:25–00:35/);
  assert.match(translated.observation, /200.00 Hz/);
  assert.match(translated.observation, /100.00 Hz/);
  const report = { summaryText: '한국어 요약', priorities: [finding] };
  assert.equal(reportDisplaySummary(report, false), translated.observation);
  assert.doesNotMatch(agentNextPractice(report, false), /[가-힣]/);
  assert.equal(report.summaryText, '한국어 요약');
});

test('English findings render in Korean without fabricating missing observations', () => {
  const text = findingText({ id: 'pitch_change', label: '평균 목소리 높이 / Mean voice pitch', observationText: 'English only' }, true);
  assert.match(text.observation, /상세 관측 자료가 없습니다/);
  assert.doesNotMatch(text.observation, /00:|Hz|200/);
  assert.equal(sceneText('Camera', true), '카메라');
  assert.equal(sceneText('카메라', false), 'Camera');
});


test('the main report explains an observable change and the next review action without a Hertz dump', () => {
  const rawSegments=[100,100,200,210].map((value,n)=>({segmentId:`s${n}`,startMs:n<2?n*10000:25000+(n-2)*10000,endMs:n<2?(n+1)*10000:35000+(n-2)*10000,stressScore:.6,quality:{audioValid:true,faceDetected:true},audioFeatures:{f0_mean:value},videoFeatures:{},concepts:{}}));
  const report = { summaryText: '목소리 높이는 200 Hz였습니다.', rawSegments, analysis: { coverage: .83 }, priorities: [
    { id: 'pitch_change',metric:'f0_mean',modality:'audio',selectedSegmentIds:['s2','s3'],referenceValue:100,independentObservations:2 }
  ] };
  const ko = reportDisplaySummary(report, true);
  assert.match(ko, /00:25–00:35/);
  assert.match(ko, /음높이가 상승/);
  assert.match(ko, /문장/);
  assert.doesNotMatch(ko, /Hz|200|잘못|나쁨/);
  const en = reportDisplaySummary(report, false);
  assert.doesNotMatch(en, /[가-힣]/);
  assert.match(en, /sentence/);
});

test('stress signal scores use a 100 point reference scale and never fabricate a missing score', () => {
  const { signalScore } = loadTs('../lib/report-locale.ts');
  assert.equal(signalScore(.54), '54 / 100');
  assert.equal(signalScore('0.80'), '80 / 100');
  assert.equal(signalScore(null), '—');
  assert.equal(signalScore('—'), '—');
});


test('mouth findings explain the measured opening, without inventing pronunciation problems', () => {
  const {findingGuidance} = loadTs('../lib/report-locale.ts');
  const finding = {id:'lip_tension', referenceValue:.137, independentObservations:8, observations:[
    {startMs:20000, endMs:30000, value:.203}, {startMs:30000, endMs:40000, value:.155}
  ]};
  const ko = findingGuidance(finding, true);
  assert.match(ko.observation, /00:20–00:30.*입이 벌어진 정도가 앞부분보다 컸습니다/);
  assert.match(ko.observation, /검토 구간은 2곳/);
  assert.doesNotMatch(ko.observation, /구간 차이|겹치지|긴장|불명확|8곳/);
  assert.match(ko.question, /소리와 함께.*명료도.*유지.*짧게 나눠 연습/);
  const en = findingGuidance(finding, false);
  assert.match(en.observation, /more open/);
  assert.doesNotMatch(Object.values(en).join(' '), /[가-힣]/);
  assert.match(findingGuidance({...finding, observations:[{startMs:20000,endMs:30000,value:.1}]},true).observation, /작았습니다/);
  assert.match(findingGuidance({...finding, observations:[{startMs:20000,endMs:30000,value:.137}]},true).observation, /유사했습니다/);
});

test('missing reference does not fabricate a mouth comparison or direction', () => {
  const {findingGuidance} = loadTs('../lib/report-locale.ts');
  for (const referenceValue of [null, undefined, NaN, Infinity]) {
    const view = findingGuidance({id:'lip_tension',referenceValue,observations:[{startMs:20000,endMs:30000,value:.203}]}, true);
    assert.match(view.observation, /비교할 자료가 부족/);
    assert.doesNotMatch(view.observation, /컸습니다|작았습니다|유사했습니다/);
  }
  const missing = findingGuidance({id:'lip_tension',independentObservations:8}, true);
  assert.match(missing.observation, /상세 관측 자료가 없습니다/);
  assert.doesNotMatch(missing.observation, /곳/);
});


test('new exact-measure guidance keeps jaw opening and jitter separate from legacy patterns', () => {
  const {findingGuidance} = loadTs('../lib/report-locale.ts');
  const jaw=findingGuidance({id:'v2_jaw_open',referenceValue:.1,observations:[{startMs:20000,endMs:30000,value:.3}]},true);
  assert.match(jaw.observation,/턱을 여는 움직임/);
  assert.match(jaw.question,/말이 급하게/);
  assert.doesNotMatch(jaw.question,/덜 열|줄이/);
  const jitter=findingGuidance({id:'v2_jitter',referenceValue:.01,observations:[{startMs:20000,endMs:30000,value:.02}]},false);
  assert.match(jitter.observation,/cycle-to-cycle frequency variation/);
  assert.doesNotMatch(Object.values(jitter).join(' '),/[가-힣]/);
});

test('answer changes coaching without altering the measured score', () => {
  const report = { priorities: [], observationReport: { peakSegment: { stressScore: .8 } },
    reflection: { segmentId: 'peak', answer: null } };
  const originalScore = report.observationReport.peakSegment.stressScore;
  report.reflection.answer = 'intentional';
  assert.match(agentNextPractice(report, true), /의도적으로 강조한/);
  report.reflection.answer = 'unintentional';
  assert.match(agentNextPractice(report, true), /다음 발표/);
  report.reflection.answer = 'unsure';
  assert.match(agentNextPractice(report, true), /영상을 다시 보며/);
  assert.equal(report.observationReport.peakSegment.stressScore, originalScore);
});


test('reflection preserves the selected language for advice from another saved finding', () => {
  const report = {priorities: [{id:'pitch_change', label:'평균 목소리 높이 / Mean voice pitch',
    ranges:[{startMs:20000,endMs:30000}], practiceSuggestion:'한국어 연습 제안',
    referenceValue:100, observations:[{startMs:20000,endMs:30000,value:150}]}],
    reflection:{segmentId:'peak',startMs:0,endMs:10000,answer:'intentional'}};
  assert.doesNotMatch(agentNextPractice(report, false), /[가-힣]/);
  assert.match(agentNextPractice(report, true), /한국어 연습 제안/);
});

test('report summary includes the stored thirty-second reference without changing session scores', () => {
  const report={analysis:{coverage:1,averageStress:.6},priorities:[],observationReport:{personalBaseline:{score:.4,sampleCount:3,observedMs:30000,averageDifference:.2,peakDifference:.3}}};
  const ko=reportDisplaySummary(report,true),en=reportDisplaySummary(report,false);
  assert.match(ko,/30초.*40.00\/100.*20점/);
  assert.match(en,/30s.*40.00\/100.*20 points/);
  assert.doesNotMatch(en,/[가-힣]/);
  assert.equal(report.analysis.averageStress,.6);
  assert.match(ko,/우선적으로 검토할 변화가 확인되지 않았/);
});

test('unverified saved groups cannot reappear as repeated change in either summary language',()=>{
  const report={analysis:{coverage:1},priorities:[{id:'audio:energy_variability',referenceValue:.24,observations:[{segmentId:'a',startMs:57000,endMs:67000,value:.52},{segmentId:'b',startMs:68000,endMs:78000,value:.2}]}]};
  assert.match(reportDisplaySummary(report,true),/00:57–01:07.*음성 에너지 변화.*0\.52/);
  assert.doesNotMatch(reportDisplaySummary(report,true),/변화가 있었|영상은 2곳/);
  assert.match(reportDisplaySummary(report,false),/Voice energy variation.*0\.52.*00:57–01:07/);
});

test('saved comparison gives a concrete summary without assigning an unsupported exercise', () => {
  const report = {
    analysis: { coverage: 1 },
    priorities: [],
    observationReport: { patterns: [{ id: 'pitch_variability', startMs: 10000, endMs: 20000, value: 33.4, comparisonValue: 47.2, unit: 'Hz' }] },
  };
  assert.match(reportDisplaySummary(report, true), /00:10–00:20.*33\.4 Hz.*47\.2 Hz.*낮았습니다/);
  assert.match(reportDisplaySummary(report, false), /33\.4 Hz.*00:10–00:20.*below.*47\.2 Hz/);
  assert.equal(agentNextPractice(report, true), '');
});


test('a saved intent question is shown only for a verified pitch observation at the same interval', () => {
  const rawSegments = [100, 100, 150, 151].map((value, index) => ({
    segmentId: "s" + index, startMs: index * 10000, endMs: (index + 1) * 10000,
    stressScore: .6, quality: { audioValid: true, faceDetected: true },
    audioFeatures: { f0_mean: value }, videoFeatures: {}, concepts: {},
  }));
  const reflection = { kind: 'finding', segmentId: 's2', startMs: 20000, endMs: 30000, answer: null };
  const priorities = [{ id: 'pitch_change', metric: 'f0_mean', modality: 'audio', selectedSegmentIds: ['s2', 's3'] }];
  const report = { rawSegments, priorities, reflection };
  assert.equal(reportIntentReflection(report), reflection);
  assert.equal(reportIntentReflection({ ...report, priorities: [] }), undefined);
  assert.equal(reportIntentReflection({ ...report, reflection: { ...reflection, kind: 'overall' } }), undefined);
  assert.equal(reportIntentReflection({ ...report, reflection: { ...reflection, segmentId: 's0', startMs: 0, endMs: 10000 } }), undefined);
});
