const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = ts.createSourceFile('agent-report.ts',
  fs.readFileSync(path.join(__dirname, '../lib/agent-report.ts'), 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
const declaration = source.statements.find((item) => ts.isFunctionDeclaration(item) && item.name?.text === 'reportDisplaySummary');
assert.ok(declaration);
const code = ts.transpileModule(declaration.getText(source), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText;
const reportDisplaySummary = new Function('exports', `${code}; return reportDisplaySummary;`)({});

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
