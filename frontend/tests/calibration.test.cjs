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

test('initial reference freezes after exactly three windows until explicit recalibration', () => {
  const frame = stressScore => ({stressScore, quality:{audioValid:true,faceDetected:true}});
  let samples=[];
  for (const [i,value] of [.2,.8,.4,1,.9].entries()) samples=addCalibrationSample(samples,frame(value),(i+1)*10000);
  assert.equal(samples.length,3);
  assert.equal(calibrationMedian(samples),.4);
  assert.equal(calibrationMedian([{stressScore:.2},{stressScore:.8},{stressScore:.4},{stressScore:1}]),.4);
});

test('stored initial value is reused only with valid evidence count and the same model', () => {
  const saved={score:.4,sampleCount:3,modelVersion:'v1',calibratedAt:'2026-11-03T00:00:00Z'};
  assert.equal(moduleExports.reusableCalibration(saved,'v1'),true);
  for (const invalid of [{...saved,score:NaN},{...saved,sampleCount:2},{...saved,calibratedAt:'bad'},null]) assert.equal(moduleExports.reusableCalibration(invalid,'v1'),false);
  assert.equal(moduleExports.reusableCalibration(saved,'v2'),false);
  assert.equal(saved.score,.4);
});

test('drift uses the newest comparable sessions rather than the caller order', () => {
  const calibration={score:.3,modelVersion:'v1',calibratedAt:'2026-10-01T00:00:00Z'};
  const row=(score,day)=>({score,coverage:1,sceneLabel:'Camera',modelVersion:'v1',sessionDate:`2026-10-${day}T00:00:00Z`});
  assert.equal(suggestRecalibration([row(.3,'02'),row(.5,'06'),row(.51,'04'),row(.49,'05')],calibration,'Camera'),true);
});
