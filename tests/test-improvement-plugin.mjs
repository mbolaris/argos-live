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
    'argos_proctor_answer','argos_proctor_continue','argos_proctor_submit','argos_proctor_feedback',
    'argos_adopt_external_instruction_edit']) {
    assert.equal(options.get(name)?.optional, true);
    await assert.rejects(tools.get(name).execute('unmanaged', {}, undefined), /managed host controller/);
  }
  assert.deepEqual(tools.get('argos_proctor_item').parameters.additionalProperties, false);
  assert.deepEqual(tools.get('argos_proctor_answer').parameters.additionalProperties, false);
  const adoption = tools.get('argos_adopt_external_instruction_edit').parameters;
  assert.deepEqual(Object.keys(adoption.properties),
    ['expected_sha256','previous_sha256','reason','baseline_ids','candidate_ids']);
  assert.deepEqual(adoption.additionalProperties, false);
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
} else if (args[1] === 'log' && fs.existsSync(process.env.ARGOS_CAPTURE+'.failed-log')) {
  console.log(JSON.stringify({status:'failed',message:'Campaign log entry failed; the host workload remains available.',append_outcome:'unconfirmed'}));
} else if (args[1] === 'log') {
  console.log(JSON.stringify({status:'appended',observed:'2026-10-17T00:00:00+00:00',snapshot:'/private/snapshot',note_claims_verified:false}));
} else if (args[1] === 'results' && fs.existsSync(process.env.ARGOS_CAPTURE+'.incompatible')) {
  console.log(JSON.stringify({status:'rejected',error_code:'recipe_mismatch',message:'Runs used different recipes.',
    runs:[{id:'1'.repeat(32),recipe_fingerprint:'a'.repeat(64),settings_fingerprint:'b'.repeat(64)}],
    pair_checks:{same_suite_version:true,same_recipe:false,same_coverage:true}}));
} else if (args[1] === 'openclaw') {
  const suite = args[3] || 'quick';
  const total = suite === 'challenge' || suite === 'tool-schema' || suite === 'tool-plan' || suite === 'tool-sequence' ? 40 : suite === 'standard' ? 70 : 20;
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
    summary:{correct,total,...(['tool-schema','tool-plan','tool-sequence'].includes(suite) ? {partitions:{practice:{correct:18,total:20},heldout:{correct:20,total:20}}} : {})},
    coverage:{completed:total,total,complete:true}, elapsed_seconds:12
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
    const answerTool = tools.get('argos_proctor_answer').parameters;
    assert.deepEqual(Object.keys(answerTool.properties), ['item_id', 'answer']);
    assert.deepEqual(answerTool.required, ['item_id', 'answer']);
    assert.match(tools.get('argos_proctor_item').description, /host binds answers to retrieved active items/);

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

    const schemaProgress = [];
    const schemaRun = await tools.get('argos_evaluate').execute('schema-eval', {suite:'tool-schema'}, undefined,
      (event) => schemaProgress.push(event));
    assert.match(schemaRun.content[0].text, /38\/40 passed/);
    assert.match(schemaRun.content[0].text, /unseen-vocabulary: 20\/20 \(same bundled suite, not independent validation\)/);
    assert.equal(schemaRun.details.coverage.total, 40);
    assert.equal(schemaProgress.length, 1);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'openclaw', '--suite', 'tool-schema', '--json']);
    assert.match(JSON.stringify(tools.get('argos_evaluate').parameters.properties.suite),
      /bundled held-out items; these are internal transfer checks, not independent validation/);

    const planRun = await tools.get('argos_evaluate').execute('plan-eval', {suite:'tool-plan'}, undefined,
      () => {});
    assert.match(planRun.content[0].text, /38\/40 passed/);
    assert.match(planRun.content[0].text, /unseen-vocabulary: 20\/20 \(same bundled suite, not independent validation\)/);
    assert.equal(planRun.details.coverage.total, 40);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'openclaw', '--suite', 'tool-plan', '--json']);

    const sequenceRun = await tools.get('argos_evaluate').execute('sequence-eval', {suite:'tool-sequence'}, undefined,
      () => {});
    assert.match(sequenceRun.content[0].text, /38\/40 passed/);
    assert.match(sequenceRun.content[0].text, /held-out workflows: 20\/20 \(same bundled suite, not independent validation\)/);
    assert.equal(sequenceRun.details.coverage.total, 40);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'openclaw', '--suite', 'tool-sequence', '--json']);
    assert.match(JSON.stringify(tools.get('argos_evaluate').parameters.properties.suite), /tool-sequence/);

    await tools.get('argos_compare').execute('compare', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    });
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'results', '--compare', '1'.repeat(32), '2'.repeat(32), '--json']);
    await writeFile(capture + '.incompatible', 'fixture');
    const incompatible = await tools.get('argos_compare').execute('incompatible', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    });
    assert.equal(incompatible.details.pair_checks.same_recipe, false);
    assert.match(incompatible.content[0].text, /Comparison diagnostics:/);
    assert.match(incompatible.content[0].text, /same_suite_version/);
    await rm(capture + '.incompatible', {force:true});
    await writeFile(capture + '.raw', 'raw-model fixture');
    await assert.rejects(tools.get('argos_evaluate').execute('raw', { suite: 'quick' }),
      /Raw model runs do not test assistant instructions/);
    const rawCompare = await tools.get('argos_compare').execute('raw-compare', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    });
    assert.equal(rawCompare.details.error_code, 'not_openclaw_assistant');
    assert.match(rawCompare.content[0].text, /Raw model benchmarks cannot measure changes/);
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
    const busyCompare = await tools.get('argos_compare').execute('busy-compare', {
      baseline_id:'1'.repeat(32), candidate_id:'2'.repeat(32)
    });
    assert.equal(busyCompare.details.status, 'busy');
    assert.match(busyCompare.content[0].text, /No comparison was run/);
    assert.doesNotMatch(busyCompare.content[0].text, /Raw model benchmarks cannot measure/);
    await rm(capture + '.busy', {force:true});
    await writeFile(capture + '.failed-log', 'failed log fixture');
    const failedLog = await tools.get('argos_log').execute('failed-log', {text:note});
    assert.equal(failedLog.details.status, 'failed');
    assert.match(failedLog.content[0].text, /append outcome is unconfirmed/);
    assert.doesNotMatch(failedLog.content[0].text, /Appended at host time/);
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

test('direct non-evaluation tool escalates an ignored cancellation and waits for child exit', async () => {
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
    const evaluation = tools.get('argos_log').execute('stuck-log', {text:'note'}, controller.signal);
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

test('aborting an evaluation wait leaves the detached host job running and pollable', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-plugin-job-'));
  const executable = path.join(directory, 'slow-argos.mjs');
  const capture = path.join(directory, 'child.json');
  const release = path.join(directory, 'release');
  const priorBin = process.env.ARGOS_BIN;
  const priorBinArgs = process.env.ARGOS_BIN_ARGS;
  const priorCapture = process.env.ARGOS_CAPTURE;
  const priorRelease = process.env.ARGOS_RELEASE;
  let child;
  try {
    await writeFile(executable, `import fs from 'node:fs';
const args = process.argv.slice(2);
fs.writeFileSync(process.env.ARGOS_CAPTURE, JSON.stringify({pid:process.pid,args}));
const deadline = Date.now() + 10000;
while (!fs.existsSync(process.env.ARGOS_RELEASE) && Date.now() < deadline)
  await new Promise(resolve => setTimeout(resolve, 10));
console.log(JSON.stringify({path:'/private/fixture-result.json',result:{
 id:'d'.repeat(32),suite:'openclaw-standard',suite_version:'argos-openclaw-ability/standard/fixture1',
 state:'completed',settings:{execution_path:'openclaw embedded; ephemeral state; tools denied; v2'},
 summary:{correct:68,total:70},coverage:{completed:70,total:70,complete:true}
}}));
`);
    process.env.ARGOS_BIN = process.execPath;
    process.env.ARGOS_BIN_ARGS = JSON.stringify([executable]);
    process.env.ARGOS_CAPTURE = capture;
    process.env.ARGOS_RELEASE = release;
    const pluginPath = pathToFileURL(path.resolve('openclaw-plugin/argos-improve/index.js')).href;
    const {default: register} = await import(`${pluginPath}?job-test=${Date.now()}`);
    const tools = new Map();
    register({registerTool(tool) {tools.set(tool.name, tool);}});
    assert.ok(tools.has('argos_evaluate_wait'));
    const controller = new AbortController();
    const evaluation = tools.get('argos_evaluate').execute('slow-eval', {suite:'standard'}, controller.signal);
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try { child = JSON.parse(await readFile(capture, 'utf8')); break; }
      catch { await new Promise((resolve) => setTimeout(resolve, 20)); }
    }
    assert.ok(child, 'The host evaluation process should start.');
    controller.abort();
    const started = await evaluation;
    assert.equal(started.details.status, 'running');
    assert.equal(started.details.total, 70);
    assert.match(started.details.job_id, /^[a-f0-9]{32}$/);
    const status = await tools.get('argos_evaluate_status').execute('status', {});
    assert.equal(status.details.status, 'running');
    assert.equal(status.details.job_id, started.details.job_id);
    if (process.platform !== 'win32') {
      process.kill(child.pid, 0);
    }
    await writeFile(release, 'complete');
    const completed = await tools.get('argos_evaluate_wait').execute('poll',
      {job_id:started.details.job_id});
    assert.match(completed.content[0].text, /68\/70 passed/);
    assert.equal(completed.details.coverage.completed, 70);
  } finally {
    if (child?.pid) {
      try { process.kill(process.platform === 'win32' ? child.pid : -child.pid, 'SIGKILL'); }
      catch { /* Test cleanup only. */ }
    }
    if (priorBin === undefined) delete process.env.ARGOS_BIN; else process.env.ARGOS_BIN = priorBin;
    if (priorBinArgs === undefined) delete process.env.ARGOS_BIN_ARGS; else process.env.ARGOS_BIN_ARGS = priorBinArgs;
    if (priorCapture === undefined) delete process.env.ARGOS_CAPTURE; else process.env.ARGOS_CAPTURE = priorCapture;
    if (priorRelease === undefined) delete process.env.ARGOS_RELEASE; else process.env.ARGOS_RELEASE = priorRelease;
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
    hooks.get('before_tool_call')({toolName:'argos_audit_instructions',runId:'run-1',toolCallId:'audit-1'},ctx);
    assert.deepEqual(await admission.execute('audit-1','audit',{}),{status:'appended'});
    hooks.get('before_tool_call')({toolName:'argos_adopt_external_instruction_edit',runId:'run-1',toolCallId:'adopt-1'},ctx);
    const adoption = {expected_sha256:'a'.repeat(64),previous_sha256:'b'.repeat(64),reason:'Keep tested edit.',
      baseline_ids:['1'.repeat(32),'2'.repeat(32)],candidate_ids:['3'.repeat(32),'4'.repeat(32)]};
    assert.deepEqual(await admission.execute('adopt-1','adopt',adoption),{status:'appended'});
    await hooks.get('agent_end')({},ctx);
    assert.deepEqual(requests.map((value) => value.op),['begin','tool','tool','tool','tool','ended']);
    assert.deepEqual(requests.at(-1).diagnostics,{tool_hooks:5,bound_calls:4,executions:4,
      rejected:{unknown_tool:1,missing_admission:0,invalid_call_id:0,stale_binding:0}});
    assert.equal(requests[1].run_id,'run-1');
    assert.equal(requests[1].call_id,'log-1');
    assert.equal(requests[1].turn_token,'fictional-turn');
    assert.equal(requests[1].params.text,'Unicode note 你好');
    assert.equal(requests[2].kind,'proctor_item');
    assert.deepEqual(requests[2].params,{item_id:'q1'});
    assert.equal(requests[3].kind,'audit');
    assert.deepEqual(requests[3].params,{});
    assert.equal(requests[4].kind,'adopt');
    assert.deepEqual(requests[4].params,adoption);
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

test('managed admission returns bounded evaluation jobs and supports a follow-up wait', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-admission-job-'));
  const endpoint = process.platform === 'win32' ? `\\\\.\\pipe\\argos-job-${randomUUID()}` : path.join(directory, 'host.sock');
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
      if (value.op === 'begin') response = {status:'admitted',turn_token:'turn-job'};
      else if (value.op === 'tool' && value.kind === 'evaluation')
        response = {status:'running',job_id:'b'.repeat(32),suite:'standard',completed:0,total:70};
      else if (value.op === 'tool' && value.kind === 'evaluation_wait' &&
               value.params.job_id === 'd'.repeat(32))
        response = {status:'completed',value:{status:'completed',proctor_simulation:true,
          message:'Proctor simulation only; no evaluation was started.'}};
      else if (value.op === 'tool' && value.kind === 'evaluation_wait')
        response = {status:'completed',value:{result:{id:'c'.repeat(32),state:'completed',
          suite:'openclaw-standard',suite_version:'argos-openclaw-ability/standard/test',
          settings:{execution_path:'openclaw embedded; ephemeral state; tools denied; v2'},
          summary:{correct:68,total:70},coverage:{completed:70,total:70,complete:true}},path:'/private/run.json'}};
      else response = {status:'recorded'};
      socket.end(JSON.stringify(response) + '\n');
    });
  });
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(endpoint, resolve); });
    process.env.ARGOS_CONTROLLER_SOCKET = endpoint;
    process.env.ARGOS_CONTROLLER_SECRET = 'job-bridge-secret';
    const hooks = new Map();
    const tools = new Map();
    registerPlugin({pluginConfig:{hostAdmission:true},
      registerTool(tool) {tools.set(tool.name, tool);},
      on(name, handler) {hooks.set(name, handler);}});
    const ctx = {runId:'run-job',sessionId:'session-job',sessionKey:'agent:main:host-session',trigger:'user'};
    assert.deepEqual(await hooks.get('before_agent_run')({}, ctx), {outcome:'pass'});
    hooks.get('before_tool_call')({toolName:'argos_evaluate',runId:'run-job',toolCallId:'eval-job'},ctx);
    const started = await tools.get('argos_evaluate').execute('eval-job',{suite:'standard'});
    assert.equal(started.details.status, 'running');
    assert.equal(started.details.total, 70);
    hooks.get('before_tool_call')({toolName:'argos_evaluate_wait',runId:'run-job',toolCallId:'wait-job'},ctx);
    const finished = await tools.get('argos_evaluate_wait').execute('wait-job',
      {job_id:started.details.job_id});
    assert.equal(finished.details.coverage.completed,70);
    hooks.get('before_tool_call')({toolName:'argos_evaluate_wait',runId:'run-job',toolCallId:'wait-sim'},ctx);
    const simulated = await tools.get('argos_evaluate_wait').execute('wait-sim',
      {job_id:'d'.repeat(32)});
    assert.match(simulated.content[0].text,/Proctor simulation only; no evaluation was started/);
    assert.deepEqual(requests.filter(item => item.op === 'tool').map(item => item.kind),
      ['evaluation','evaluation_wait','evaluation_wait']);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    if (priorPath === undefined) delete process.env.ARGOS_CONTROLLER_SOCKET; else process.env.ARGOS_CONTROLLER_SOCKET = priorPath;
    if (priorSecret === undefined) delete process.env.ARGOS_CONTROLLER_SECRET; else process.env.ARGOS_CONTROLLER_SECRET = priorSecret;
    await rm(directory, {recursive:true, force:true});
  }
});

test('managed busy comparisons and failed logs are reported without false success or category errors', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-admission-status-'));
  const endpoint = process.platform === 'win32' ? `\\\\.\\pipe\\argos-status-${randomUUID()}` : path.join(directory, 'host.sock');
  const priorPath = process.env.ARGOS_CONTROLLER_SOCKET;
  const priorSecret = process.env.ARGOS_CONTROLLER_SECRET;
  const server = net.createServer((socket) => {
    socket.setEncoding('utf8');
    let raw = '';
    socket.on('data', (chunk) => {
      raw += chunk;
      if (!raw.endsWith('\n')) return;
      const request = JSON.parse(raw);
      let response;
      if (request.op === 'begin') response = {status:'admitted',turn_token:'turn-status'};
      else if (request.op === 'tool' && request.kind === 'compare')
        response = {status:'busy',message:'Host workload needs attention',recovery_required:false};
      else if (request.op === 'tool' && request.kind === 'log')
        response = {status:'completed',value:{status:'failed',
          message:'Campaign log entry failed; the host workload remains available.',append_outcome:'unconfirmed'}};
      else response = {status:'recorded'};
      socket.end(JSON.stringify(response) + '\n');
    });
  });
  try {
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(endpoint, resolve); });
    process.env.ARGOS_CONTROLLER_SOCKET = endpoint;
    process.env.ARGOS_CONTROLLER_SECRET = 'status-bridge-secret';
    const hooks = new Map();
    const tools = new Map();
    registerPlugin({pluginConfig:{hostAdmission:true},
      registerTool(tool) {tools.set(tool.name, tool);},
      on(name, handler) {hooks.set(name, handler);}});
    const ctx = {runId:'run-status',sessionId:'session-status',sessionKey:'agent:main:host-session',trigger:'user'};
    assert.deepEqual(await hooks.get('before_agent_run')({}, ctx), {outcome:'pass'});
    hooks.get('before_tool_call')({toolName:'argos_compare',runId:'run-status',toolCallId:'compare-busy'},ctx);
    const busy = await tools.get('argos_compare').execute('compare-busy', {
      baseline_id:'1'.repeat(32),candidate_id:'2'.repeat(32)
    });
    assert.equal(busy.details.status,'busy');
    assert.match(busy.content[0].text,/No comparison was run/);
    assert.match(busy.content[0].text,/Retry after the current host operation finishes/);
    assert.doesNotMatch(busy.content[0].text,/Raw model benchmarks cannot measure/);

    hooks.get('before_tool_call')({toolName:'argos_log',runId:'run-status',toolCallId:'log-failed'},ctx);
    const failed = await tools.get('argos_log').execute('log-failed',{text:'note'});
    assert.equal(failed.details.status,'failed');
    assert.equal(failed.details.append_outcome,'unconfirmed');
    assert.match(failed.content[0].text,/inspect IMPROVEMENT-LOG.md before retrying/);
    assert.doesNotMatch(failed.content[0].text,/Appended at host time/);
    await hooks.get('agent_end')({},ctx);
  } finally {
    if (priorPath === undefined) delete process.env.ARGOS_CONTROLLER_SOCKET;
    else process.env.ARGOS_CONTROLLER_SOCKET = priorPath;
    if (priorSecret === undefined) delete process.env.ARGOS_CONTROLLER_SECRET;
    else process.env.ARGOS_CONTROLLER_SECRET = priorSecret;
    await new Promise((resolve) => server.close(resolve));
    await rm(directory,{recursive:true,force:true});
  }
});
