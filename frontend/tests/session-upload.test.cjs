const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { Upload } = require('tus-js-client');

test('resumable video upload recovers a failed second chunk without resending the first', async () => {
  const bytes = Buffer.alloc(7 * 1024 * 1024, 91);
  let offset = 0, failed = false, heads = 0;
  const accepted = [];
  const server = http.createServer(async (req, res) => {
    assert.equal(req.headers.authorization, 'Bearer synthetic-token');
    res.setHeader('Tus-Resumable', '1.0.0');
    if (req.method === 'HEAD') {
      heads++;
      res.setHeader('Upload-Offset', offset);
      res.setHeader('Upload-Length', bytes.length);
      res.writeHead(200).end(); return;
    }
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    const data = Buffer.concat(chunks);
    if (req.method === 'PATCH' && !failed) { failed = true; res.writeHead(503).end(); return; }
    assert.equal(Number(req.headers['upload-offset'] ?? 0), offset);
    assert.deepEqual(data, bytes.subarray(offset, offset + data.length));
    accepted.push(data.length); offset += data.length;
    res.setHeader('Upload-Offset', offset);
    if (req.method === 'POST') res.setHeader('Location', '/upload/one');
    res.writeHead(req.method === 'POST' ? 201 : 204).end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const endpoint = `http://127.0.0.1:${server.address().port}/upload`;
    const module = { exports: {} };
    const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../lib/session-upload.ts'), 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const client = { auth: { getSession: async () => ({data:{session:{access_token:'synthetic-token'}}}) } };
    class LocalUpload extends Upload { constructor(file, options) {
      assert.equal(options.chunkSize, 6*1024*1024);
      assert.ok(!Object.keys(options.headers).some(key=>key.toLowerCase()==='authorization'), 'XHR must set its token only once per request');
      assert.match(options.metadata.objectName, /^synthetic\//);
      super(bytes, {...options, endpoint, retryDelays:[0,10], uploadSize:bytes.length});
    } }
    const old = process.env.NEXT_PUBLIC_SUPABASE_URL;
    process.env.NEXT_PUBLIC_SUPABASE_URL = 'https://synthetic-upload.test';
    const oldKey=process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY='synthetic-key';
    try {
      new Function('require','module','exports',code)(name => {
        if(name==='tus-js-client')return {Upload:LocalUpload};
        if(name==='@/lib/supabase/client')return {getSupabaseBrowserClient:()=>client};
        throw new Error(name);
      },module,module.exports);
      const progress=[];
      await module.exports.uploadSessionVideo('synthetic/ten-minute.webm', new Blob([bytes],{type:'video/webm'}), p=>progress.push(p));
      assert.equal(offset, bytes.length); assert.equal(failed,true); assert.ok(heads>=1);
      assert.deepEqual(accepted,[6*1024*1024,1024*1024]);
      assert.equal(progress.at(-1).sent,bytes.length);
    } finally { if(oldKey===undefined)delete process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;else process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=oldKey; if(old===undefined)delete process.env.NEXT_PUBLIC_SUPABASE_URL;else process.env.NEXT_PUBLIC_SUPABASE_URL=old; }
  } finally { await new Promise(resolve=>server.close(resolve)); }
});
