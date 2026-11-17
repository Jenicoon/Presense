const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const code = ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname,'../lib/practice-measurements.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const moduleValue = {exports:{}};
new Function('require','module','exports',code)(() => ({}),moduleValue,moduleValue.exports);
const {comparePracticeMeasurement}=moduleValue.exports;
const original={modelVersion:'same',metricDefinitionVersion:'metric',conceptDefinitionVersion:'concept',modality:'audio',metric:'f0_mean',value:120};
const measured={...original,quality:{audioValid:true,faceDetected:true},audioFeatures:{f0_mean:150}};
test('comparison returns a numeric difference without a delivery grade',()=>{
 assert.deepEqual(comparePracticeMeasurement(original,measured),{original:120,retry:150,difference:30});
});
test('mismatching models, definitions, missing values and bad modality quality cannot be compared',()=>{
 for(const patch of [{modelVersion:'other'},{metricDefinitionVersion:'other'},{conceptDefinitionVersion:'other'},{quality:{audioValid:false,faceDetected:true}},{audioFeatures:{f0_mean:NaN}},{audioFeatures:{}}]){
  assert.equal(comparePracticeMeasurement(original,{...measured,...patch}),null);
 }
});
