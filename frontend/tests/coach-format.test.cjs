const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

test("coach messages round long zero-to-one measurements without changing other numbers", () => {
  const module = { exports: {} };
  const code = ts.transpileModule(
    fs.readFileSync(path.join(__dirname, "../lib/coach-format.ts"), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  new Function("module", "exports", code)(module, module.exports);
  assert.equal(
    module.exports.formatCoachMeasurementNumbers(
      "눈꺼풀 조임 움직임: 이전 0.256412, 현재 0.310715. 스트레스 75 / 100.",
    ),
    "눈꺼풀 조임 움직임: 이전 0.26, 현재 0.31. 스트레스 75 / 100.",
  );
});

test("previous-session evidence is displayed as a readable comparison summary", () => {
  const module = { exports: {} };
  const code = ts.transpileModule(
    fs.readFileSync(path.join(__dirname, "../lib/coach-format.ts"), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
  ).outputText;
  new Function("module", "exports", code)(module, module.exports);
  const formatted = module.exports.formatCoachMeasurementNumbers(
    "같은 기준의 스트레스 신호: 이전 72 / 100, 현재 75 / 100. 이 차이는 좋고 나쁨의 결론보다 음성·영상 측정값을 함께 살펴볼 위치를 정하는 데 사용합니다. 보고서에서 선택된 검토 항목: 이전 선택된 검토 항목 없음; 현재 선택된 검토 항목 없음. 눈꺼풀 조임 움직임: 이전 0.256412, 현재 0.310715.",
  );
  assert.equal(
    formatted,
    "이전 발표와 비교\n• 스트레스 신호: 이전 72 / 100 → 현재 75 / 100\n  ↳ 이 차이는 좋고 나쁨의 결론이 아니라, 함께 살펴볼 음성·영상 측정값을 찾는 데 사용합니다.\n• 보고서 검토 항목: 이전 없음 → 현재 없음\n• 눈꺼풀 조임 움직임: 이전 0.26 → 현재 0.31",
  );
});
