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
    if (id === '@/lib/measurement-labels') return loadTs('../lib/measurement-labels.ts');
    if (id === '@/lib/report-locale') return loadTs('../lib/report-locale.ts');
    return {};
  });
  return exports;
}
const { reportDisplaySummary, agentNextPractice } = loadTs('../lib/agent-report.ts');
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
  const report = { summaryText: '목소리 높이는 200 Hz였습니다.', analysis: { coverage: .83 }, priorities: [
    { id: 'pitch_change', referenceValue: 100, independentObservations: 3, observations: [{ startMs: 25000, endMs: 35000, value: 200 }] }
  ] };
  const ko = reportDisplaySummary(report, true);
  assert.match(ko, /00:25–00:35/);
  assert.match(ko, /목소리가 더 높아/);
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
  assert.match(ko.observation, /00:20–00:30.*입이 벌어진 정도가 앞부분보다 컸어요/);
  assert.match(ko.observation, /영상은 2곳/);
  assert.doesNotMatch(ko.observation, /구간 차이|겹치지|긴장|불명확|8곳/);
  assert.match(ko.question, /입 모양만으로.*소리와 함께.*지금 방식을 유지.*짧게 나눠 연습/);
  const en = findingGuidance(finding, false);
  assert.match(en.observation, /more open/);
  assert.doesNotMatch(Object.values(en).join(' '), /[가-힣]/);
  assert.match(findingGuidance({...finding, observations:[{startMs:20000,endMs:30000,value:.1}]},true).observation, /작았어요/);
  assert.match(findingGuidance({...finding, observations:[{startMs:20000,endMs:30000,value:.137}]},true).observation, /비슷했어요/);
});

test('missing reference does not fabricate a mouth comparison or direction', () => {
  const {findingGuidance} = loadTs('../lib/report-locale.ts');
  for (const referenceValue of [null, undefined, NaN, Infinity]) {
    const view = findingGuidance({id:'lip_tension',referenceValue,observations:[{startMs:20000,endMs:30000,value:.203}]}, true);
    assert.match(view.observation, /비교할 자료가 부족/);
    assert.doesNotMatch(view.observation, /컸어요|작았어요|비슷했어요/);
  }
  const missing = findingGuidance({id:'lip_tension',independentObservations:8}, true);
  assert.match(missing.observation, /상세 관측 자료가 없습니다/);
  assert.doesNotMatch(missing.observation, /곳/);
});
