const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const code = ts.transpileModule(fs.readFileSync(path.join(__dirname,'../lib/agent-report.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const m={exports:{}};
new Function('require','module','exports',code)(name => name === '@/lib/supabase/client'
 ? {getSupabaseBrowserClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'local-test'}}})}})}
 : {INFERENCE_URL:'http://example.test'},m,m.exports);
const {FeedbackRequestError,feedbackFailureMessage,authorizeReportFeedback,analysisResultsAvailable}=m.exports;
test('consent conflict is distinguished from server connectivity and feedback persistence',()=>{
 assert.match(feedbackFailureMessage(new FeedbackRequestError(409,'consent'),true),/동의를 저장하지 못/);
 assert.match(feedbackFailureMessage(new TypeError('fetch failed'),true),/서버에 연결하지 못/);
 assert.match(feedbackFailureMessage(new Error('write failed'),true,true),/피드백은 생성됐지만/);
 assert.match(feedbackFailureMessage(new FeedbackRequestError(401,'generation'),false),/sign-in expired/);
});
test('consent HTTP failures retain their stage and status',async()=>{
 const before=global.fetch;
 global.fetch=async()=>new Response(JSON.stringify({detail:{code:'report_consent_conflict'}}),{status:409});
 try {await assert.rejects(authorizeReportFeedback('test-session'),e=>e instanceof FeedbackRequestError && e.status===409 && e.stage==='consent' && e.code==='report_consent_conflict');}
 finally {global.fetch=before;}
});
test('analysis results stay disabled until requested AI feedback is ready and saved',()=>{
 const base={generationState:'ready',analysisStatus:'complete'};
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'failed'}},true,true),false);
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'partial'}},true,true),false);
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'ready'}},true,false),false);
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'ready'}},true,true,true),false);
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'ready'}},true,true,false,'retry'),false);
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'ready'}},true,true),true);
 assert.equal(analysisResultsAvailable({...base,reportFeedback:{status:'blocked'}},false,true),true);
});
