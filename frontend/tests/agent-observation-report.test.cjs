const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const source = ts.createSourceFile('agent-observation-report.tsx',
  fs.readFileSync(path.join(__dirname, '../components/agent-observation-report.tsx'), 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declaration = source.statements.find((item) => ts.isFunctionDeclaration(item) && item.name?.text === 'conceptBarPercent');
assert.ok(declaration);
const code = ts.transpileModule(declaration.getText(source), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const conceptBarPercent = new Function('exports', `${code}; return conceptBarPercent;`)({});

test('concept bars use a fixed one-unit scale', () => {
  assert.equal(conceptBarPercent(0.2), 20);
  assert.equal(conceptBarPercent(0.6), 60);
  assert.equal(conceptBarPercent(1), 100);
  assert.equal(conceptBarPercent(1.4), 100);
  assert.equal(conceptBarPercent(-0.2), 0);
});
