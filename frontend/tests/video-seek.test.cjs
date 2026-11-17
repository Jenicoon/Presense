const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require('typescript');
const exports_={};
new Function('exports',ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname,'../lib/video-seek.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText)(exports_);
class Video extends EventTarget {
  readyState=1; duration=60; currentTime=0; plays=0;
  play(){this.plays++;return Promise.resolve();}
  load(){} scrollIntoView(){}
}
test('clicking a real time seeks in seconds and starts playback even with unknown WebM duration',()=>{
  const video=new Video();video.duration=Infinity;
  assert.equal(exports_.seekRecording(video,25000),true);
  assert.equal(video.currentTime,25);assert.equal(video.plays,1);
});
test('before metadata loads, the most recent click is the one that plays',()=>{
  const video=new Video();video.readyState=0;
  exports_.seekRecording(video,10000);exports_.seekRecording(video,30000);
  assert.equal(video.plays,0);
  video.readyState=1;video.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(video.currentTime,30);assert.equal(video.plays,1);
});
test('missing video and invalid times cannot report a successful seek',()=>{
  assert.equal(exports_.seekRecording(null,1000),false);
  assert.equal(exports_.seekRecording(new Video(),NaN),false);
  assert.equal(exports_.seekRecording(new Video(),-1),false);
});
