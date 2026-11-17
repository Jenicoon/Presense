const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const ts = require("typescript");
const source = ts.createSourceFile(
  "timeline.tsx",
  fs.readFileSync(
    __dirname + "/../components/session-agent-report.tsx",
    "utf8",
  ),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
let fn, mergeFn;
function visit(n) {
  if (ts.isFunctionDeclaration(n) && n.name?.text === "mergeTimeline")
    mergeFn = n.getText(source).replace("export ", "");
  if (ts.isFunctionDeclaration(n) && n.name?.text === "withGaps")
    fn = n.getText(source).replace("export ", "");
  ts.forEachChild(n, visit);
}
visit(source);
const js = ts.transpileModule(fn, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;
const withGaps = new Function(js + ";return withGaps")();
test("actual timeline preserves low intervals, overlap cells and unobserved gaps", () => {
  const result = withGaps(
    [
      { startMs: 5000, endMs: 10000, stressScore: 0.2 },
      { startMs: 10000, endMs: 15000, stressScore: 0.5 },
      { startMs: 20000, endMs: 30000, stressScore: 0.8 },
    ],
    35000,
  );
  assert.deepEqual(
    result.map((c) => c.stressScore),
    [null, 0.2, 0.5, null, 0.8, null],
  );
  assert.equal(result[3].startMs, 15000);
  assert.equal(result[3].endMs, 20000);
});
test("no observed results means one explicit gap, never a zero score", () => {
  assert.deepEqual(withGaps([], 20000), [
    { startMs: 0, endMs: 20000, stressScore: null },
  ]);
});

const mergeTimeline = new Function(
  ts.transpileModule(mergeFn, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText + ";return mergeTimeline",
)();
test("dense overlapping results are grouped for display without bridging a gap or mutating originals", () => {
  const cells = Array.from({ length: 1200 }, (_, i) => ({
    startMs: i * 100 + (i >= 600 ? 10000 : 0),
    endMs: (i + 1) * 100 + (i >= 600 ? 10000 : 0),
    stressScore: i % 2 ? 0.2 : 0.8,
  }));
  const merged = mergeTimeline(cells, 130000);
  assert.ok(merged.length <= 130);
  assert.equal(cells.length, 1200);
  assert.ok(!merged.some((c) => c.startMs < 60000 && c.endMs > 70000));
  assert.equal(
    withGaps(merged, 130000).filter((c) => c.stressScore === null).length,
    1,
  );
});

const chartSource = ts.createSourceFile('chart.tsx', fs.readFileSync(__dirname + '/../components/stress-chart.tsx', 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const runFunction = chartSource.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === 'timelineRuns');
const timelineRuns = new Function(ts.transpileModule(runFunction.getText(chartSource).replace('export ', ''), {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText + ';return timelineRuns')();

test('line chart uses real interval times and breaks before unobserved time', () => {
  const cells = [
    {startMs:5000,endMs:10000,stressScore:.2},
    {startMs:10000,endMs:15000,stressScore:.8},
    {startMs:15000,endMs:20000,stressScore:null},
    {startMs:20000,endMs:30000,stressScore:.4},
  ];
  const runs = timelineRuns(cells, 35000);
  assert.deepEqual(runs.map(run => run.map(cell => cell.startMs)), [[5000,10000],[20000]]);
  assert.deepEqual(runs.flat().map(cell => cell.stressScore), [.2,.8,.4]);
  assert.equal(cells.length, 4);
});

test('line chart keeps a real zero but never substitutes invalid or missing scores', () => {
  const runs = timelineRuns([
    {startMs:0,endMs:5000,stressScore:0},
    {startMs:5000,endMs:10000,stressScore:NaN},
    {startMs:10000,endMs:15000,stressScore:.5},
    {startMs:15000,endMs:25000,stressScore:.7},
  ], 20000);
  assert.deepEqual(runs.flat().map(cell => cell.stressScore), [0,.5]);
  assert.equal(runs.length, 2);
  assert.deepEqual(timelineRuns([{startMs:0,endMs:10000,stressScore:null}],10000), []);
});
