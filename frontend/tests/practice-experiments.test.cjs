const test=require('node:test');
const assert=require('node:assert/strict');
const ts=require('typescript');const fs=require('node:fs');const path=require('node:path');
const js=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/practice-experiments.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const module_={exports:{}};
new Function('require','module','exports',js)(name=>{
 if(name.endsWith('practice-experiments.json')||name.endsWith('concept-v2-guidance.json'))return {default:JSON.parse(fs.readFileSync(path.join(__dirname,'../../shared',path.basename(name)),'utf8'))};
 throw new Error(name);
},module_,module_.exports);
const {practiceMethods,practiceMethod,verifiedPracticePlan}=module_.exports;
const finding={id:'v2_jitter',evidenceStatus:'cited_excerpt',evidenceIds:['paper'],observations:[{segmentId:'real',startMs:30000,endMs:40000}],practicePlan:{kind:'comparison_experiment',source:'ai_selected',strategyId:'clear_phrases',segmentId:'real',startMs:30000,endMs:40000,definitionVersion:'comparison-experiments-v1',language:'ko',instructions:{reason:'실제 관측에 따른 연습 이유입니다.',goal:'해당 구간의 전달을 비교하기',steps:['원본에서 비교할 문장을 고르세요.','같은 문장을 다시 녹화해 비교하세요.'],question:'어느 버전에서 끝 단어가 더 잘 구분되나요?'}}};
const report={language:'ko',synthesisStatus:'generated',evidence:[{id:'paper'}]};
test('each method gives a concrete goal, three steps and one comparison question in both languages',()=>{
 for(const id of ['v2_jitter','v2_eye_squint','v2_jaw_open','v2_mean_f0','gaze'])for(const method of practiceMethods(id))for(const ko of [true,false]){
  const item=practiceMethod(method,ko);assert.equal(item.steps.length,3);assert.ok(item.question.endsWith('?'));assert.ok(item.goal);
  if(!ko)assert.doesNotMatch(JSON.stringify(item),/[가-힣]/);
 }
 assert.match(practiceMethod('clear_phrases',true).question,/끝 단어/);
});
test('AI-selected practice requires a cited source and the exact verified observation',()=>{
 assert.equal(verifiedPracticePlan(report,finding).strategyId,'clear_phrases');
 for(const changed of [{segmentId:'invented'},{startMs:31000},{strategyId:'expression'},{source:'html'},{definitionVersion:'unknown'},{instructions:undefined},{language:'en'}])assert.equal(verifiedPracticePlan(report,{...finding,practicePlan:{...finding.practicePlan,...changed}}),null);
 assert.equal(verifiedPracticePlan({...report,evidence:[]},finding),null);
 assert.equal(verifiedPracticePlan({...report,synthesisStatus:'unavailable'},finding),null);
});
test('recorder renders generated instructions verbatim instead of selecting a canned task',()=>{
 const module={exports:{}};
 const js=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../components/report-practice.tsx'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 new Function('require','module','exports',js)(name=>{
  if(name==='react'||name==='react/jsx-runtime')return require(name);
  if(name==='@/lib/coaching')return {clock:()=> '00:30'};
  return {};
 },module,module.exports);
 const instructions={reason:'앞부분과 다른 음높이를 보인 실제 구간에 대한 맞춤 비교입니다.',goal:'고른 단어의 강조 방식 한 가지 비교하기',steps:['비교할 단어를 본인이 고르세요.','그 단어에만 강조를 주어 녹화하세요.','원본과 새 촬영을 번갈아 들어보세요.'],question:'선택한 단어는 어느 버전에서 구분됐나요?'};
 const html=require('react-dom/server').renderToStaticMarkup(require('react').createElement(module.exports.ReportPractice,{sessionId:'synthetic',findingId:'v2_mean_f0',interval:{startMs:30000,endMs:40000},videoUrl:'blob:synthetic',ko:true,strategyId:'contrast',instructions}));
 for(const text of [instructions.reason,instructions.goal,...instructions.steps,instructions.question])assert.ok(html.includes(text));
 assert.doesNotMatch(html,/같은 문장에 쉼 한 곳만 더해/);
});
