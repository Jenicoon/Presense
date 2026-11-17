const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const module_ = { exports: {} };
new Function('exports', ts.transpileModule(fs.readFileSync(path.join(__dirname, '../lib/report-windows.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(module_.exports);
const { summarizeWindows, observedTimeline, reviewIntervals } = module_.exports;
const window_ = (startMs, endMs, stressScore, valid = true) => ({
  startMs, endMs, stressScore, quality: { audioValid: valid, faceDetected: valid },
});
test('summary integrates overlapping time once and leaves unobserved bins empty', () => {
  const rows = summarizeWindows([window_(0, 10000, .2), window_(5000, 15000, .8), window_(0,10000,.9,false)], 60000);
  assert.equal(rows[0].observedMs, 15000);
  assert.ok(Math.abs(rows[0].score-.5) < 1e-12);
  assert.equal(rows[1].score, null);
});
test('ten-minute sliding results reduce to twenty summaries without changing or removing originals', () => {
  const original = Array.from({ length: 591 }, (_, i) => window_(i*1000, i*1000+10000, .4));
  const copy = structuredClone(original);
  const result = summarizeWindows(original, 600000);
  assert.equal(result.length, 20);
  assert.equal(result.reduce((sum,row) => sum+row.observedMs,0), 600000);
  assert.ok(result.every(row => Math.abs(row.score-.4) < 1e-10));
  assert.deepEqual(original, copy);
});
test('the immediate recording chart retains actual times, overlap scores and missing time', () => {
  const rows=[window_(5000,15000,.2),window_(10000,20000,.8),window_(20000,30000,.9,false)];
  assert.deepEqual(observedTimeline(rows,40000),[
    {startMs:0,endMs:5000,stressScore:null},{startMs:5000,endMs:10000,stressScore:.2},
    {startMs:10000,endMs:15000,stressScore:.5},{startMs:15000,endMs:20000,stressScore:.8},
    {startMs:20000,endMs:40000,stressScore:null},
  ]);
});
test('replay choices are real valid intervals and preserve the peak without inventing ranges', () => {
  const rows=Array.from({length:91},(_,i)=>({...window_(i*1000,i*1000+10000,i===17?.9:.3),segmentId:String(i)}));
  rows.push({...window_(100000,110000,.99,false),segmentId:'invalid'});
  const choices=reviewIntervals(rows,120000);
  assert.ok(choices.length < 10);
  assert.ok(choices.some(row=>row.segmentId==='17'));
  assert.ok(choices.every(row=>rows.includes(row) && row.quality.audioValid));
});
