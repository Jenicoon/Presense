const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require('typescript');
const code=ts.transpileModule(fs.readFileSync(__dirname+'/../lib/supabase/data.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
function load(state) {
  const client={from(table){assert.equal(table,'user_calibrations');return {
    upsert:async row=>{state.row=structuredClone(row);return {error:null};},
    select:()=>({eq:()=>({maybeSingle:async()=>({data:state.row??null,error:null})})}),
    update:change=>({eq:async()=>{state.row={...state.row,...change};return {error:null};}}),
  };}};
  const exports={};
  new Function('exports','require',code)(exports,id=>id==='@/lib/supabase/client'?{getSupabaseBrowserClient:()=>client}:{});
  return exports;
}
test('saved initial reference is restored on reload and prompting never changes it',async()=>{
  const state={};
  const initial={score:.4,sampleCount:3,modelVersion:'v1',calibratedAt:'2026-11-03T00:00:00Z'};
  await load(state).saveUserCalibration('test-user',initial);
  const restored=await load(state).loadUserCalibration('test-user');
  assert.equal(restored.score,.4);assert.equal(restored.sampleCount,3);assert.equal(restored.modelVersion,'v1');
  await load(state).markCalibrationPrompted('test-user','2026-11-03T01:00:00Z');
  assert.equal((await load(state).loadUserCalibration('test-user')).score,.4);
  await load(state).saveUserCalibration('test-user',{...initial,score:.6});
  assert.equal((await load(state).loadUserCalibration('test-user')).score,.6);
});
