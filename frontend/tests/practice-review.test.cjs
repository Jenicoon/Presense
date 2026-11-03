const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
function compile(file, requireDependency) {
  const code = ts.transpileModule(fs.readFileSync(__dirname+'/../'+file,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  new Function('exports','require',code)(exports,requireDependency);
  return exports;
}
const {PracticeReviewForm} = compile('components/practice-review-form.tsx',require);
const card = {type:'practice_review',practiceId:'p',attemptSessionId:'a',checks:[{id:'boundary',label:'의미가 끝나는 곳에서 멈췄나요?'},{id:'start',label:'다음 문장을 새로 시작했나요?'}]};
test('review starts unanswered and asks for both conditions and the saved actions',()=>{
  const html=renderToStaticMarkup(React.createElement(PracticeReviewForm,{card,ko:true,busy:false,onSubmit(){}}));
  assert.equal((html.match(/<select/g)||[]).length,4);
  assert.match(html,/다시 말한 내용/);assert.match(html,/카메라·마이크 환경/);
  assert.match(html,/다음 문장을 새로 시작/);assert.match(html,/확인 결과 저장/);
  assert.match(html,/<button[^>]*disabled/);
  assert.equal((html.match(/value="" selected/g)||[]).length,4);
});
test('review controls follow the selected UI language',()=>{
  const english={...card,checks:[{id:'boundary',label:'Did you pause at a completed thought?'},{id:'start',label:'Did the next sentence start separately?'}]};
  const html=renderToStaticMarkup(React.createElement(PracticeReviewForm,{card:english,ko:false,busy:false,onSubmit(){}}));
  assert.doesNotMatch(html,/[가-힣]/);assert.match(html,/Unable to assess/);assert.match(html,/Save my review/);
});
test('selected answers and attempt identity reach the coaching API without being converted to a grade',async()=>{
  const review={practiceId:'p',attemptSessionId:'a',sameContent:'same',sameEnvironment:'same',answers:{boundary:'yes',start:'partly'}};
  let sent;
  const originalFetch=global.fetch, originalWindow=global.window;
  global.window={dispatchEvent(){}};
  global.fetch=async(url,options)=>{sent={url,body:JSON.parse(options.body)};return {ok:true,json:async()=>({conversationState:{stage:'comparison_ready'}})};};
  try {
    const api=compile('lib/coaching.ts',id=>id==='@/lib/supabase/client'?{getSupabaseBrowserClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'local-test'}}})}})}:id==='@/lib/live-signal'?{INFERENCE_URL:'http://127.0.0.1:8016'}:require(id));
    await api.actCoach({sessionId:'s',action:'submit_practice_review',language:'ko',revision:4,deliveryReview:review});
    assert.equal(sent.url,'http://127.0.0.1:8016/agent/coach');assert.deepEqual(sent.body.deliveryReview,review);
    assert.equal(sent.body.revision,4);assert.equal(sent.body.outcome,undefined);
  } finally {global.fetch=originalFetch;global.window=originalWindow;}
});
