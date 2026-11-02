const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../lib/calibration.ts'), 'utf8');
const moduleExports = {};
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
new Function('exports', js)(moduleExports);
const { addCalibrationSample, calibrationMedian, suggestRecalibration } = moduleExports;

test('baseline uses the median of three valid nonoverlapping windows', () => {
  const frame = (stressScore, audioValid = true, faceDetected = true) =>
    ({ stressScore, quality: { audioValid, faceDetected } });
  let samples = [];
  samples = addCalibrationSample(samples, frame(.2), 10000);
  samples = addCalibrationSample(samples, frame(.9), 11000);
  samples = addCalibrationSample(samples, frame(.9, false), 20000);
  samples = addCalibrationSample(samples, frame(.8), 20000);
  samples = addCalibrationSample(samples, frame(.4), 30000);
  assert.equal(samples.length, 3);
  assert.equal(calibrationMedian(samples), .4);
  assert.equal(calibrationMedian(samples.slice(0, 2)), null);
});

test('recalibration suggestion requires three comparable post-calibration sessions', () => {
  const calibration = { score: .3, modelVersion: 'v1', calibratedAt: '2026-10-01T00:00:00Z' };
  const row = (score, date, overrides = {}) => ({ score, coverage: .8, sceneLabel: 'Camera', modelVersion: 'v1', sessionDate: date, ...overrides });
  const rows = [row(.51, '2026-10-05T00:00:00Z'), row(.5, '2026-10-04T00:00:00Z'), row(.49, '2026-10-03T00:00:00Z')];
  assert.equal(suggestRecalibration(rows, calibration, 'Camera'), true);
  assert.equal(suggestRecalibration(rows, { ...calibration, lastPromptedAt: '2026-10-03T12:00:00Z' }, 'Camera'), false);
  assert.equal(suggestRecalibration([row(.1, '2026-10-06T00:00:00Z'), ...rows.slice(1)], calibration, 'Camera'), false);
  assert.equal(suggestRecalibration([row(.51, '2026-10-06T00:00:00Z', { coverage: .2 }), ...rows.slice(1)], calibration, 'Camera'), false);
});
