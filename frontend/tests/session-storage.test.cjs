const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../lib/supabase/data.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function setup(options = {}) {
  const events = [];
  const row = { id: 'record', title: 'Practice', session_date: '2026-09-09', duration_seconds: 30,
    result: 'Stable', stress_average: 0.4, diagnosis: 'Analysis', timeline: [20, 40], video_path: 'user/video.webm',
    agent_report: options.agentReport ?? null };
  const client = {
    auth: {
      getUser: async () => ({ data: { user: { id: 'user' } }, error: null }),
      getSession: async () => ({ data: { session: { user: { id: 'user' }, access_token: 'test' } } }),
    },
    storage: { from: () => ({
      upload: async (name) => { events.push(['upload', name]); return { error: options.uploadError }; },
      remove: async (names) => { events.push(['remove', names]); return { error: null }; },
      createSignedUrl: async () => ({ data: options.signError ? null : { signedUrl: 'https://example.test/video' }, error: options.signError }),
    }) },
    from: (table) => ({
      insert: async (value) => {
        events.push([table, value]);
        if (table === 'diagnosis_history' && options.summaryThrows) throw new Error('offline');
        return { error: table === 'presentation_records' ? options.insertError : null };
      },
      upsert: (value, upsertOptions) => ({
        abortSignal: async () => { events.push([table, value, upsertOptions]); return { error: options.insertError }; },
      }),
      update: (value) => {
        const query = {
          eq: () => query, is: () => query, select: () => query,
          abortSignal: async () => {
            events.push(['video_path', value]);
            if (options.conflictOnce && !options.hadConflict) { options.hadConflict = true; row.agent_report = { ...row.agent_report, coachingSession: {revision: 3}, storageRevision: 5 }; return { data: [], error: null }; }
            if (value.agent_report) row.agent_report = value.agent_report;
            return { data: [{id:row.id}], error: null };
          },
        };
        return query;
      },
      select: () => {
        const query = { order: async () => ({ data: [row], error: null }), eq: () => query, single: () => query,
          maybeSingle: async () => ({ data: row, error: null }),
          abortSignal: () => ({ single: async () => ({ data: row, error: null }) }) };
        return query;
      },
    }),
  };
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)((name) => {
    if (name === '@/lib/supabase/client') return { getSupabaseBrowserClient: () => client };
    if (name === '@/lib/session-drafts') return { removeSessionDraft: async () => undefined };
    if (name === '@/lib/session-upload') return { uploadSessionVideo: async (name, video) => {
      const { error } = await client.storage.from('session-videos').upload(name, video);
      if (error) throw new Error(error.message);
    } };
    if (name === '@/lib/app-data') return {};
    if (name === '@/lib/agent-report') return { agentNextPractice: () => 'Adjusted practice' };
    throw new Error(`Unexpected import: ${name}`);
  }, module, module.exports);
  return { api: module.exports, events };
}
const input = { title: 'Practice', durationSeconds: 30, averageStress: 0.4, result: 'Stable',
  diagnosis: 'Analysis', nextAction: 'Practice', sceneLabel: 'Camera', timeline: [20, 40],
  video: new Blob(['test recording'], { type: 'video/webm' }) };

test('session is persisted before upload and its video path is attached afterwards', async () => {
  const { api, events } = setup();
  await api.savePracticeSession(input);
  assert.equal(events[0][0], 'presentation_records');
  assert.equal(events[0][1].video_path, null);
  assert.equal(events[1][0], 'upload');
  assert.deepEqual(events[2], ['video_path', { video_path: events[1][1] }]);
  assert.equal(events[0][2].ignoreDuplicates, true);
  assert.deepEqual(events[0][1].timeline, input.timeline);
});
test('upload failure preserves the saved session and returns a recoverable warning', async () => {
  const { api, events } = setup({ uploadError: { message: 'The object exceeded the maximum allowed size' } });
  const result = await api.savePracticeSession(input);
  assert.match(result.warning, /세션 기록은 저장/);
  assert.equal(events[0][0], 'presentation_records');
  assert.equal(events.filter(e => e[0] === 'remove').length, 0);
});
test('failed base persistence never starts an upload', async () => {
  const { api, events } = setup({ insertError: { message: 'offline' } });
  await assert.rejects(api.savePracticeSession(input), /offline/);
  assert.equal(events.filter(e => e[0] === 'upload').length, 0);
});
test('analysis-only save does not upload video', async () => {
  const { api, events } = setup();
  await api.savePracticeSession({ ...input, video: null });
  assert.equal(events[0][0], 'presentation_records');
  assert.equal(events[0][1].video_path, null);
});
test('generated report is stored with its session and returned in history', async () => {
  const report = { schemaVersion: '1.0', sessionId: 'session-report', summaryText: 'Observed voice change.', priorities: [] };
  const { api, events } = setup({ agentReport: report });
  await api.savePracticeSession({ ...input, id: report.sessionId, agentReport: report, video: null });
  assert.equal(events[0][1].id, report.sessionId);
  assert.deepEqual(events[0][1].agent_report, report);
  const [record] = await api.loadSessionHistory();
  assert.deepEqual(record.agentReport, report);
  const dashboard = await api.loadDashboardData();
  assert.deepEqual(dashboard.presentationRecords[0].agentReport, report);
});
test('summary failure after persistence is a warning, not a failed save', async () => {
  const { api } = setup({ summaryThrows: true });
  const result = await api.savePracticeSession(input);
  assert.match(result.warning, /offline/);
});
test('history retains a saved video path and explains signed URL failure', async () => {
  const { api } = setup({ signError: { message: 'Access denied' } });
  const [record] = await api.loadSessionHistory();
  assert.equal(record.videoPath, 'user/video.webm');
  assert.equal(record.videoUrl, null);
  assert.equal(record.durationSeconds, 30);
  assert.equal(record.videoError, 'Access denied');
  assert.deepEqual(record.timeline, [20, 40]);
});

test('a report with no usable observations stores null rather than a fabricated zero',async()=>{const {api,events}=setup();await api.savePracticeSession({...input,video:null,averageStress:null});assert.equal(events[0][1].stress_average,null);});

test('attaching a generated report never overwrites a concurrently uploaded video', async () => {
  const { api, events } = setup();
  const report = { sessionId: 'record', summaryText: 'Ready', analysis: {averageStress: .4}, priorities: [] };
  await api.saveGeneratedSessionReport('record', report);
  const patch = events.at(-1)[1];
  assert.deepEqual(patch.agent_report, { ...report, storageRevision: 1 });
  assert.equal(patch.stress_average, .4);
  assert.equal(Object.hasOwn(patch, 'video_path'), false);
});
test('attaching a video preserves the independently generated report', async () => {
  const { api, events } = setup();
  await api.uploadPracticeVideo('record', input.video);
  assert.deepEqual(Object.keys(events.at(-1)[1]), ['video_path']);
});

test('new reports and notes preserve coaching state in the existing JSON column', async () => {
  const old = {storageRevision:2,coachingSession:{revision:4},selfFeedback:'old note'};
  const {api,events}=setup({agentReport:old});
  await api.saveGeneratedSessionReport('record',{sessionId:'record',summaryText:'Fresh',analysis:{averageStress:.4},priorities:[],selfFeedback:'stale local note'});
  let stored=events.at(-1)[1].agent_report;
  assert.deepEqual(stored.coachingSession,{revision:4});assert.equal(stored.storageRevision,3);assert.equal(stored.selfFeedback,'old note');
  await api.saveSessionNote('record','Updated reflection');stored=events.at(-1)[1].agent_report;
  assert.deepEqual(stored.coachingSession,{revision:4});assert.equal(stored.selfFeedback,'Updated reflection');assert.equal(stored.storageRevision,4);
});
test('a concurrent coaching turn is retained after report-save conflict and retry',async()=>{
 const {api,events}=setup({agentReport:{storageRevision:4,coachingSession:{revision:2}},conflictOnce:true});
 await api.saveSessionNote('record','my note');
 const stored=events.at(-1)[1].agent_report;
 assert.deepEqual(stored.coachingSession,{revision:3});assert.equal(stored.selfFeedback,'my note');assert.equal(stored.storageRevision,6);
 assert.equal(events.filter(e=>e[0]==='video_path').length,2);
});

test('coaching retry stays out of presentation history but its comparison video remains accessible', async () => {
  const { api } = setup({agentReport:{reportInput:{practiceContext:{sessionId:'parent',practiceId:'exercise'}}}});
  assert.deepEqual(await api.loadSessionHistory(), []);
  assert.equal(await api.loadSessionVideoUrl('record'), 'https://example.test/video');
});

test('comparison video lookup reports a storage failure instead of returning an unusable URL', async () => {
  const { api } = setup({signError:new Error('video unavailable')});
  await assert.rejects(api.loadSessionVideoUrl('record'), /video unavailable/);
});
