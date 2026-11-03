const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Exercise the real request handler with in-memory media and a mock model.
const source = ts.createSourceFile('dashboard.tsx', fs.readFileSync(path.join(__dirname, '../components/dashboard-shell.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'requestLiveFrame') handler = node.getText(source);
  ts.forEachChild(node, visit);
}
visit(source);
assert.ok(handler);
const js = ts.transpileModule(handler, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
function setup(respond = async () => ({ stressScore: 0.4, confidence: 0.6, modelVersion: 'v1', quality: { audioValid: true, faceDetected: true } }), overrides = {}) {
  const results = [], phases = [];
  const refs = { generation: { current: 0 }, inFlight: { current: false }, active: { current: false }, baseline: { current: null }, samples: { current: [] } };
  const env = {
    recordingActiveRef: refs.active, preparationFrameRef: refs.baseline,
    calibrationSamplesRef: refs.samples, calibrationModelVersion: 'v1',
    addCalibrationSample: (samples, frame, capturedAtMs) => [...samples, { stressScore: frame.stressScore, capturedAtMs }],
    calibrationMedian: (samples) => samples.length >= 3 ? 0.4 : null,
    setCalibrationCount() {},
    inferInFlightRef: refs.inFlight,
    analysisGenerationRef: refs.generation,
    inferenceAbortRef: { current: null },
    frameBufferRef: { current: Array.from({ length: 16 }, () => new Blob(['frame'])) },
    getRecentAudioPcm: () => new Float32Array(160000),
    setLiveStatus: () => {}, setPreparationPhase: (phase) => phases.push(phase),
    setModelConnected: () => {}, SIGNAL_SOURCE: 'live', calibration: null,
    inferMultimodalFrame: respond, applyFrame: (frame) => results.push(frame),
    sessionStartedAtRef: { current: performance.now() - 11_000 },
    reportSegmentsRef: { current: [] },
    toReportSegment: (frame, index, endMs) => ({ frame, index, endMs }),
    ...overrides,
  };
  return { request: new Function(...Object.keys(env), `${js}; return requestLiveFrame;`)(...Object.values(env)), results, phases, refs };
}
test('preparation checks the model without adding any recorded results', async () => {
  const state = setup();
  await state.request(true);
  assert.deepEqual(state.phases, ['analyzing', 'collecting']);
  assert.deepEqual(state.results, []);
  assert.equal(state.refs.baseline.current.stressScore, 0.4);
  assert.equal(state.refs.samples.current.length, 1);
});
test('normal recording stores the current model result', async () => {
  const state = setup();
  await state.request();
  assert.equal(state.results.length, 1);
  assert.deepEqual(state.phases, []);
});
test('failed preparation does not enable completion or record a score', async () => {
  const state = setup(async () => { throw new Error('offline'); });
  await state.request(true);
  assert.deepEqual(state.phases, ['analyzing', 'error']);
  assert.deepEqual(state.results, []);
  assert.equal(state.refs.inFlight.current, false);
});
test('response from a discarded preparation is ignored', async () => {
  let resolve;
  const state = setup(() => new Promise((done) => { resolve = done; }));
  const pending = state.request(true);
  state.refs.generation.current++;
  resolve({ stressScore: 0.7, confidence: 0.7 });
  await pending;
  assert.deepEqual(state.phases, ['analyzing']);
  assert.deepEqual(state.results, []);
});

test('a partial audio window is not sent to inference', async () => {
  let requests = 0;
  const state = setup(async () => { requests++; }, {
    getRecentAudioPcm: () => new Float32Array(159000),
  });
  await state.request();
  assert.equal(requests, 0);
  assert.equal(state.refs.inFlight.current, false);
});

function loadFunction(name, env) {
  let found;
  function find(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) found = node.getText(source);
    ts.forEachChild(node, find);
  }
  find(source);
  assert.ok(found);
  const code = ts.transpileModule(found, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(...Object.keys(env), `${code}; return ${name};`)(...Object.values(env));
}

test('report response makes the session summary use the same model average and peak', async () => {
  let report = { averageStress: 0.45, peakValue: 60, peakBin: 0, peakPhase: 'Open' };
  let received;
  const request = { sessionId: 'same', durationMs: 40000 };
  const generate = loadFunction('requestAgentReport', {
    reportRequestRef: { current: request }, sessionIdRef: { current: 'same' },
    setAgentReportLoading() {}, setAgentReportError() {},
    generateAgentReport: async () => ({ observationReport: {
      averageStressScore: 0.71,
      peakSegment: { startMs: 19000, endMs: 29000, stressScore: 0.78 },
    } }),
    setAgentReport: (value) => { received = value; },
    setReport: (update) => { report = update(report); },
    PHASES: ['Open', 'Build', 'Core', 'Close'], lang: 'ko',
    attemptContextRef: {current:null}, window: {dispatchEvent() {}}, CustomEvent: class {},
  });
  await generate();
  assert.equal(received.observationReport.averageStressScore, report.averageStress);
  assert.equal(report.peakValue, 78);
  assert.equal(report.peakBin, 5);
  assert.equal(report.peakPhase, 'Build');
});

test('video collection fills its 16-frame window in 10 seconds', async () => {
  let tick, interval;
  const frames = { current: [] };
  const start = loadFunction('startCollection', {
    startAudioMeter: () => {}, collectionTickRef: { current: null },
    analysisGenerationRef: { current: 0 }, collectionBusyRef: { current: false },
    captureFrameBlob: async () => new Blob(['frame']), frameBufferRef: frames,
    setCollectedFrames: () => {}, setLiveStatus: () => {},
    window: { setInterval: (fn, ms) => { tick = fn; interval = ms; return 1; } },
  });
  start({});
  for (let i = 0; i < 16; i++) await tick();
  assert.equal(frames.current.length, 16);
  assert.equal(interval * 16, 10000);
  await tick();
  assert.equal(frames.current.length, 16);
});

test('audio uses only the latest ten seconds and returns 16 kHz PCM', () => {
  const read = loadFunction('getRecentAudioPcm', {
    audioChunksRef: { current: [new Float32Array(4800).fill(1), new Float32Array(480000).fill(2)] },
    audioSampleRateRef: { current: 48000 },
  });
  const audio = read();
  assert.equal(audio.length, 160000);
  assert.ok(audio.every((sample) => sample === 2));
});

test('a preparation response finishing after start cannot replace the starting baseline or add a score', async () => {
  let resolve;
  const state = setup(() => new Promise((done) => { resolve = done; }));
  const baseline = { stressScore: 0.3, confidence: 0.8 };
  state.refs.baseline.current = baseline;
  const pending = state.request(true);
  state.refs.active.current = true;
  resolve({ stressScore: 0.9, confidence: 0.9 });
  await pending;
  assert.equal(state.refs.baseline.current, baseline);
  assert.deepEqual(state.results, []);
  assert.equal(state.refs.inFlight.current, false);
});

test('late inference from an ended session cannot enter the next session', async () => {
  let resolve;
  const state = setup(() => new Promise((done) => { resolve = done; }));
  const pending = state.request();
  state.refs.generation.current++;
  state.refs.active.current = true;
  resolve({ stressScore: 0.95, confidence: 0.9 });
  await pending;
  assert.deepEqual(state.results, []);
  assert.equal(state.refs.baseline.current, null);
});

test('stopping clears media and baseline, invalidates requests, and stops timers', () => {
  const controller = new AbortController();
  const env = {
    recordingActiveRef: { current: true }, preparationFrameRef: { current: { stressScore: 0.8 } },
    calibrationSamplesRef: { current: [{ stressScore: .8 }] }, setCalibrationCount() {},
    analysisGenerationRef: { current: 1 }, inferenceAbortRef: { current: controller },
    inferInFlightRef: { current: true }, audioChunksRef: { current: [new Float32Array(100)] },
    frameBufferRef: { current: [new Blob(['old'])] }, collectionTickRef: { current: 1 },
    collectionBusyRef: { current: true }, rafRef: { current: null }, tickRef: { current: 2 },
    audioContextRef: { current: null }, analyserRef: { current: {} }, audioProcessorRef: { current: {} },
    setCollectedFrames() {}, setAudioSeconds() {}, setVoiceDetected() {}, setAudioRunning() {}, setAudioLevel() {},
    window: { clearInterval() {} },
  };
  loadFunction('stopAnalysis', env)();
  assert.equal(controller.signal.aborted, true);
  assert.equal(env.analysisGenerationRef.current, 2);
  assert.equal(env.preparationFrameRef.current, null);
  assert.deepEqual(env.calibrationSamplesRef.current, []);
  assert.equal(env.recordingActiveRef.current, false);
  assert.deepEqual(env.audioChunksRef.current, []);
  assert.deepEqual(env.frameBufferRef.current, []);
  assert.equal(env.collectionTickRef.current, null);
  assert.equal(env.tickRef.current, null);
});


test('a 30-second live recording retains multiple arrived windows including identical outputs', async()=>{
  const segments=[]; const sessionStart=performance.now()-10_000;
  const state=setup(async()=>({stressScore:segments.length===1?.8:.3,confidence:.8,quality:{audioValid:true,faceDetected:true}}), {
    reportSegmentsRef:{current:segments}, sessionStartedAtRef:{current:sessionStart},
    toReportSegment:(frame,index,endMs)=>({segmentId:`capture-${index}`,startMs:endMs-10000,endMs,stressScore:frame.stressScore})
  });
  for(const elapsed of [10000,20000,30000]) {
    // The handler records capture time before inference returns.
    const old=performance.now;
    Object.defineProperty(performance,'now',{value:()=>sessionStart+elapsed,configurable:true});
    await state.request();
    Object.defineProperty(performance,'now',{value:old,configurable:true});
  }
  assert.deepEqual(segments.map(s=>s.stressScore),[.3,.8,.3]);
  assert.deepEqual(segments.map(s=>[s.startMs,s.endMs]),[[0,10000],[10000,20000],[20000,30000]]);
});

test('microphone analysis can run with a silent output sink and still retain captured PCM',()=>{
  let processor;const sinks=[];const chunks=[];const audioContextRef={current:null};let seconds=0;
  class AudioContext {
    constructor(){this.state='running';this.sampleRate=48000;this.destination={};}
    setSinkId(sink){sinks.push(sink);return Promise.resolve();}
    createAnalyser(){return {frequencyBinCount:256,getByteFrequencyData(){}};}
    createMediaStreamSource(){return {connect(){}};}
    createScriptProcessor(){processor={connect(){}};return processor;}
  }
  const start=loadFunction('startAudioMeter',{audioContextRef,window:{AudioContext},setAudioRunning(){},setVoiceDetected(){},audioChunksRef:{current:chunks},setAudioSeconds:v=>seconds=v,audioSampleRateRef:{current:48000},analyserRef:{current:null},audioProcessorRef:{current:null},setAudioLevel(){},rafRef:{current:null},requestAnimationFrame:()=>1});
  start({});processor.onaudioprocess({inputBuffer:{getChannelData:()=>new Float32Array(48000).fill(.1)}});
  assert.deepEqual(sinks,[{type:'none'}]);assert.equal(chunks[0].length,48000);assert.equal(seconds,1);
});

test('completed initial measurement does not submit more windows or change its reference', async () => {
  let requests=0;
  const state=setup(async()=>{requests++;return {stressScore:.9};});
  state.refs.samples.current=[{stressScore:.2},{stressScore:.8},{stressScore:.4}];
  await state.request(true);
  assert.equal(requests,0);
  assert.equal(state.refs.samples.current.length,3);
  assert.deepEqual(state.results,[]);
});
