const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = ts.createSourceFile('agent-observation-report.tsx',
  fs.readFileSync(path.join(__dirname, '../components/agent-observation-report.tsx'), 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declarations = source.statements.filter(item => ts.isFunctionDeclaration(item) && ['conceptBarPercent','conceptDisplayRange','fixedUnit'].includes(item.name?.text));
const declaration = declarations.find(item=>item.name.text==='conceptBarPercent');
assert.ok(declaration);
const code = ts.transpileModule(declarations.map(item=>item.getText(source)).join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const { conceptBarPercent, conceptDisplayRange, fixedUnit } = new Function('exports', `${code}; return {conceptBarPercent,conceptDisplayRange,fixedUnit};`)({});

test('concept bars respect the explicitly displayed range', () => {
  assert.equal(conceptBarPercent(0.2), 20);
  assert.equal(conceptBarPercent(0.6), 60);
  assert.equal(conceptBarPercent(1), 100);
  assert.equal(conceptBarPercent(1.4), 100);
  assert.equal(conceptBarPercent(-0.2), 0);
});

test('estimates outside one unit receive a visible scale without changing their value', () => {
  const values=[.54,.31,.69,.28,.01,.55,1.14];
  const range=conceptDisplayRange(values);
  assert.deepEqual(range,[0,1.5]);
  assert.ok(Math.abs(conceptBarPercent(1.14,...range)-76)<1e-10);
  const negativeRange=conceptDisplayRange([-.2,.4]);
  assert.deepEqual(negativeRange,[-.5,1]);
  assert.ok(conceptBarPercent(-.2,...negativeRange)>0);
  assert.equal(values.at(-1),1.14);
});

test('small nonzero measurements remain nonzero and use localized units', () => {
  assert.equal(fixedUnit(.0004,'ratio',true),'0.0004 비율');
  assert.equal(fixedUnit(35.24,'semitones',true),'35.24 반음');
  assert.equal(fixedUnit(.02,'ratio',false),'0.02 ratio');
});
