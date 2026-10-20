import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import net from 'node:net';
import { randomUUID } from 'node:crypto';
import { registerAdmission } from '../openclaw-plugin/argos-improve/admission.js';
import registerPlugin from '../openclaw-plugin/argos-improve/index.js';

test('dedicated Proctor tools are registered as optional managed-only tools', async () => {
  const tools = new Map();
  const options = new Map();
  registerPlugin({registerTool(tool, metadata) { tools.set(tool.name, tool); options.set(tool.name, metadata); }});
  for (const name of ['argos_proctor_start','argos_proctor_status','argos_proctor_item',
    'argos_proctor_answer','argos_proctor_continue','argos_proctor_submit','argos_proctor_feedback']) {
    assert.equal(options.get(name)?.optional, true);
    await assert.rejects(tools.get(name).execute('unmanaged', {}, undefined), /managed host controller/);
  }
  assert.deepEqual(tools.get('argos_proctor_item').parameters.additionalProperties, false);
  assert.deepEqual(tools.get('argos_proctor_answer').parameters.additionalProperties, false);
});

test('plugin tools call the installed Argos benchmark commands', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-plugin-'));
  const executable = path.join(directory, 'fake-argos.mjs');
  const capture = path.join(directory, 'args.json');
  const priorBin = process.env.ARGOS_BIN;
  const priorBinArgs = process.env.ARGOS_BIN_ARGS;
  const priorCapture = process.env.ARGOS_CAPTURE;
  try {
    await writeFile(executable, `import fs from 'node:fs';
const args = process.argv.slice(2);
fs.writeFileSync(process.env.ARGOS_CAPTURE, JSON.stringify(args));
if (fs.existsSync(process.env.ARGOS_CAPTURE+'.busy')) {
  console.log(JSON.stringify({status:'busy',message:'Another host workload is active',recovery_required:false}));
  process.exit(75);
} else if (args[1] === 'log') {
  console.log(JSON.stringify({status:'appended',observed:'2026-10-17T00:00:00+00:00',snapshot:'/private/snapshot',note_claims_verified:false}));
} else if (args[1] === 'openclaw') {
  const suite = args[3] || 'quick';
  const total = suite === 'challenge' ? 40 : suite === 'standard' ? 70 : 20;
  const correct = total - 2;
  process.stderr.write('x'.repeat(200000) + '\\n');
  console.error(JSON.stringify({phase:'unrelated',completed:0,total}));
  console.error(JSON.stringify({phase:'asking',completed:-1,total}));
  console.error(JSON.stringify({phase:'asking',completed:total,total}));
  console.error(JSON.stringify({phase:'scored',completed:1,total:999}));
  console.error(JSON.stringify({phase:'scored', completed:1, total, receipt:{score:true, output:'fixture answer'}}));
  console.log(JSON.stringify({path:'/private/fixture-result.json', result:{
    id:'a'.repeat(32), suite:fs.existsSync(process.env.ARGOS_CAPTURE+'.raw')?'quick':'openclaw-'+suite, suite_version:'argos-openclaw-ability/'+suite+'/fixture1', state:'completed',
    settings:{suite_sha256:'b'.repeat(64),execution_path:'openclaw embedded; ephemeral state; tools denied; v2'}, prompt_fingerprint:{workspace_agents_sha256:'c'.repeat(64)},
    summary:{correct,total}, coverage:{completed:total,total,complete:true}, elapsed_seconds:12
  }}));
} else {
  console.log(JSON.stringify({kind:'ability',suite_version:fs.existsSync(process.env.ARGOS_CAPTURE+'.raw')?'raw/quick/1':'argos-openclaw-ability/quick/fixture1',settings:{execution_path:'openclaw embedded; ephemeral state; tools denied; v2'},workspace_agents_changed:false, rows:[]}));
}
`);
    process.env.ARGOS_BIN = process.execPath;
    process.env.ARGOS_BIN_ARGS = JSON.stringify([executable]);
    process.env.ARGOS_CAPTURE = capture;
    const pluginPath = pathToFileURL(path.resolve('openclaw-plugin/argos-improve/index.js')).href;
    const { default: register } = await import(`${pluginPath}?test=${Date.now()}`);
    const tools = new Map();
    register({ registerTool(tool) { tools.set(tool.name, tool); } });

    const cancelled = new AbortController();
    cancelled.abort();
    await assert.rejects(tools.get('argos_evaluate').execute('aborted-before-start',
      {suite:'quick'}, cancelled.signal), /cancelled before dispatch/);
    await assert.rejects(readFile(capture), {code:'ENOENT'});

    const progress = [];
    const evaluated = await tools.get('argos_evaluate').execute('eval', { suite: 'quick' }, undefined,
      (event) => progress.push(event));
    assert.match(evaluated.content[0].text, /18\/20 passed/);
    assert.equal(evaluated.details.suite_sha256, 'b'.repeat(64));
    assert.equal(progress.length, 1);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'openclaw', '--suite', 'quick', '--json']);

    const challengeProgress = [];
    const challenged = await tools.get('argos_evaluate').execute('challenge', {suite:'challenge'}, undefined,
      (event) => challengeProgress.push(event));
    assert.match(challenged.content[0].text, /38\/40 passed/);
    assert.equal(challenged.details.coverage.total, 40);
    assert.equal(challengeProgress.length, 1);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'openclaw', '--suite', 'challenge', '--json']);

    await tools.get('argos_compare').execute('compare', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    });
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'results', '--compare', '1'.repeat(32), '2'.repeat(32), '--json']);
    await writeFile(capture + '.raw', 'raw-model fixture');
    await assert.rejects(tools.get('argos_evaluate').execute('raw', { suite: 'quick' }),
      /Raw model runs do not test assistant instructions/);
    await assert.rejects(tools.get('argos_compare').execute('raw-compare', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    }), /Raw model runs do not test assistant instructions/);
    const note = 'Hypothesis: check output format.\n## Next\nMeasure baseline.';
    const logged = await tools.get('argos_log').execute('log', { text: note });
    assert.equal(logged.details.note_claims_verified, false);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'log', '--text', note, '--json']);
    await writeFile(capture + '.busy', 'busy fixture');
    const busy = await tools.get('argos_evaluate').execute('busy-eval', {suite:'quick'});
    assert.equal(busy.details.status, 'busy');
    assert.match(busy.content[0].text, /No evaluation started/);
    const busyLog = await tools.get('argos_log').execute('busy-log', {text:note});
    assert.match(busyLog.content[0].text, /No note appended/);
  } finally {
    if (priorBin === undefined) delete process.env.ARGOS_BIN;
    else process.env.ARGOS_BIN = priorBin;
    if (priorBinArgs === undefined) delete process.env.ARGOS_BIN_ARGS;
    else process.env.ARGOS_BIN_ARGS = priorBinArgs;
    if (priorCapture === undefined) delete process.env.ARGOS_CAPTURE;
    else process.env.ARGOS_CAPTURE = priorCapture;
    await rm(directory, { recursive: true, force: true });
  }
});

test('direct evaluation escalates an ignored cancellation and waits for child exit', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-plugin-cancel-'));
  const executable = path.join(directory, 'stuck-argos.mjs');
  const capture = path.join(directory, 'child.json');
  const priorBin = process.env.ARGOS_BIN;
  const priorBinArgs = process.env.ARGOS_BIN_ARGS;
  const priorCapture = process.env.ARGOS_CAPTURE;
  let child;
  try {
    await writeFile(executable, `import fs from 'node:fs';
import {spawn} from 'node:child_process';
process.on('SIGTERM', () => {});
const descendant = process.platform === 'win32' ? undefined : spawn(process.execPath,
  ['-e', 'process.on("SIGTERM",()=>{});setInterval(()=>{},1000)'], {stdio:'inherit'});
fs.writeFileSync(process.env.ARGOS_CAPTURE, JSON.stringify({pid:process.pid,descendant:descendant?.pid}));
setInterval(() => {}, 1000);
`);
    process.env.ARGOS_BIN = process.execPath;
    process.env.ARGOS_BIN_ARGS = JSON.stringify([executable]);
    process.env.ARGOS_CAPTURE = capture;
    const pluginPath = pathToFileURL(path.resolve('openclaw-plugin/argos-improve/index.js')).href;
    const { default: register } = await import(`${pluginPath}?cancel-test=${Date.now()}`);
    const tools = new Map();
    register({registerTool(tool) { tools.set(tool.name, tool); }});
    const controller = new AbortController();
    const evaluation = tools.get('argos_evaluate').execute('stuck-eval', {suite:'quick'}, controller.signal);
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        child = JSON.parse(await readFile(capture, 'utf8'));
        break;
      } catch { await new Promise((resolve) => setTimeout(resolve, 50)); }
    }
    assert.ok(child, 'Benchmark child should have started before cancellation.');
    controller.abort();
    let timeout;
    try {
      await Promise.race([
        assert.rejects(evaluation, /did not complete/),
        new Promise((_, reject) => { timeout = setTimeout(() => reject(
          new Error('Cancelled benchmark did not drain within the test bound.')), 12_000); })
      ]);
    } finally { clearTimeout(timeout); }
    if (process.platform !== 'win32') {
      for (const pid of [child.pid, child.descendant]) {
        let gone = false;
        for (let attempt = 0; attempt < 20; attempt += 1) {
          try { process.kill(pid, 0); }
          catch (error) { if (error.code === 'ESRCH') { gone = true; break; } throw error; }
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        assert.ok(gone, 'The full benchmark process group must be gone before the tool settles.');
      }
    }
  } finally {
    if (child?.pid) {
      try { process.kill(process.platform === 'win32' ? child.pid : -child.pid, 'SIGKILL'); }
      catch { /* Test cleanup only; the production assertion reports the failure. */ }
    }
    if (priorBin === undefined) delete process.env.ARGOS_BIN;
    else process.env.ARGOS_BIN = priorBin;
    if (priorBinArgs === undefined) delete process.env.ARGOS_BIN_ARGS;
    else process.env.ARGOS_BIN_ARGS = priorBinArgs;
    if (priorCapture === undefined) delete process.env.ARGOS_CAPTURE;
    else process.env.ARGOS_CAPTURE = priorCapture;
    await rm(directory, {recursive:true, force:true});
  }
});

test('managed hooks bind tool-call identity and cannot release the host lease', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-admission-'));
  const endpoint = process.platform === 'win32' ? `\\\\.\\pipe\\argos-admission-${randomUUID()}` : path.join(directory, 'host.sock');
  const priorPath = process.env.ARGOS_CONTROLLER_SOCKET;
  const priorSecret = process.env.ARGOS_CONTROLLER_SECRET;
  const requests = [];
  const server = net.createServer((socket) => {
    socket.setEncoding('utf8');
    let raw = '';
    socket.on('data', (chunk) => {
      raw += chunk;
      if (!raw.endsWith('\n')) return;
      const value = JSON.parse(raw);
      requests.push(value);
      let response;
      if (value.op === 'begin') response = requests.length === 1 ?
        {status:'admitted',turn_token:'fictional-turn'} : {status:'busy'};
      else if (value.op === 'tool') {
        socket.write(JSON.stringify({status:'progress',progress:{phase:'asking',completed:0,total:20}}) + '\n');
        response = {status:'completed',value:{status:'appended'}};
      }
      else response = {status:'recorded'};
      socket.end(JSON.stringify(response) + '\n');
    });
  });
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(endpoint, resolve); });
    process.env.ARGOS_CONTROLLER_SOCKET = endpoint;
    process.env.ARGOS_CONTROLLER_SECRET = 'fictional-bridge-secret';
    const hooks = new Map();
    const admission = registerAdmission({pluginConfig:{hostAdmission:true}, on(name, handler) {hooks.set(name,handler);}});
    const ctx = {runId:'run-1',sessionId:'session-1',sessionKey:'agent:main:host-session',trigger:'user'};
    assert.deepEqual(await hooks.get('before_agent_run')({}, ctx), {outcome:'pass'});
    assert.equal(hooks.get('before_tool_call')({toolName:'exec',runId:'run-1',toolCallId:'exec-1'},ctx).block,true);
    assert.equal(requests.length,1);
    hooks.get('before_tool_call')({toolName:'argos_log',runId:'run-1',toolCallId:'log-1'},ctx);
    const updates = [];
    assert.deepEqual(await admission.execute('log-1','log',{text:'Unicode note 你好'},undefined,
      (update) => updates.push(update)),{status:'appended'});
    assert.equal(updates.length,1);
    assert.match(updates[0].content[0].text,/Working on challenge 1\/20/);
    await assert.rejects(admission.execute('log-1','log',{text:'replay'}),/no current host admission/);
    hooks.get('before_tool_call')({toolName:'argos_proctor_item',runId:'run-1',toolCallId:'exam-item'},ctx);
    assert.deepEqual(await admission.execute('exam-item','proctor_item',{item_id:'q1'}),{status:'appended'});
    await hooks.get('agent_end')({},ctx);
    assert.deepEqual(requests.map((value) => value.op),['begin','tool','tool','ended']);
    assert.equal(requests[1].run_id,'run-1');
    assert.equal(requests[1].call_id,'log-1');
    assert.equal(requests[1].turn_token,'fictional-turn');
    assert.equal(requests[1].params.text,'Unicode note 你好');
    assert.equal(requests[2].kind,'proctor_item');
    assert.deepEqual(requests[2].params,{item_id:'q1'});
    assert.equal((await hooks.get('before_agent_run')({}, {...ctx,runId:'run-2'})).outcome,'block');
    assert.ok(requests.every((value) => value.auth === 'fictional-bridge-secret'));
  } finally {
    if (priorPath === undefined) delete process.env.ARGOS_CONTROLLER_SOCKET;
    else process.env.ARGOS_CONTROLLER_SOCKET = priorPath;
    if (priorSecret === undefined) delete process.env.ARGOS_CONTROLLER_SECRET;
    else process.env.ARGOS_CONTROLLER_SECRET = priorSecret;
    await new Promise((resolve) => server.close(resolve));
    await rm(directory,{recursive:true,force:true});
  }
});
