import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const patcher = path.join(root, 'scripts/patch-openclaw-liveness.mjs');
const activitySource = `const events = [];
const owner = {runId:'fixture-run',sessionId:'fixture-session',sessionKey:'fixture-key',active:true};
const activityByRunId = new Map([['fixture-run',{activeEmbeddedRuns:new Map([['fixture-session',{generation:7}]])}]]);
const activeDiagnosticOwners = new Map([[7,{owner}]]);
function resolveCurrentDiagnosticOwner(value) { return value.active; }
function emitCoreSemanticRunProgressDiagnosticEvent(event) { events.push(event); }
export { events };
export function captureDiagnosticToolProgress(event) {
\tconst runId = event.runId;
\tconst activity = runId ? activityByRunId.get(runId) : void 0;
\tconst generation = event.sessionId ? activity?.activeEmbeddedRuns.get(event.sessionId)?.generation : void 0;
\tconst owner = generation ? activeDiagnosticOwners.get(generation)?.owner : void 0;
\tif (!runId || !owner || owner.runId !== runId || owner.sessionKey !== event.sessionKey || !resolveCurrentDiagnosticOwner(owner)) return;
\treturn () => {
\t\tif (resolveCurrentDiagnosticOwner(owner)) emitCoreSemanticRunProgressDiagnosticEvent({
\t\t\trunId,
\t\t\tsessionId: owner.sessionId,
\t\t\tsessionKey: owner.sessionKey,
\t\t\treason: \`tool:\${event.toolName}:completed\`
\t\t}, owner);
\t};
}`;
const wrapperSource = `import { captureDiagnosticToolProgress, events } from './diagnostic-run-activity-fixture.mjs';
const eventBase = {runId:'fixture-run',sessionId:'fixture-session',sessionKey:'fixture-key',toolName:'argos_evaluate'};
const terminalDiagnostic = {type:'tool.execution.completed'};
const toolCallId = 'fixture-call';
const ctx = {runId:'fixture-run'};
const executeParams = {};
const executionArgs = [];
function recordToolExecutionStarted() {}
export { events };
export function makeProgress(normalizedToolName, signal, onUpdate) {
\t\t\tconst recordProgress = captureDiagnosticToolProgress(eventBase);
\t\t\trecordToolExecutionStarted(toolCallId, ctx?.runId);
\t\t\tconst args = [
\t\t\t\ttoolCallId,
\t\t\t\texecuteParams,
\t\t\t\tsignal,
\t\t\t\t\t\tonUpdate,
\t\t\t\t\t\t...executionArgs
\t\t\t];
\t\t\tif (terminalDiagnostic.type === "tool.execution.completed" && !signal?.aborted) recordProgress?.();
\t\t\treturn args[3];
}`;

async function fixture(t, version = '2026.10.4') {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-openclaw-liveness-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const dist = path.join(directory, 'dist');
  await mkdir(dist);
  await writeFile(path.join(directory, 'package.json'), JSON.stringify({name:'openclaw', version}));
  const activity = path.join(dist, 'diagnostic-run-activity-fixture.mjs');
  const wrapper = path.join(dist, 'agent-tools.before-tool-call-fixture.mjs');
  await writeFile(activity, activitySource);
  await writeFile(wrapper, wrapperSource);
  return {directory, activity, wrapper};
}

test('patch tracks live Argos progress, preserves owner fencing and completion', async (t) => {
  const sample = await fixture(t);
  execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'});
  const activity = await readFile(sample.activity, 'utf8');
  const wrapper = await readFile(sample.wrapper, 'utf8');
  assert.match(activity, /return \(phase = "completed"\)/);
  assert.match(activity, /resolveCurrentDiagnosticOwner\(owner\)/);
  assert.match(activity, /reason: `tool:\$\{event\.toolName\}:\$\{phase\}`/);
  assert.match(wrapper, /normalizedToolName === "argos_evaluate"/);
  assert.match(wrapper, /now - lastArgosProgressAt >= 30000/);
  assert.match(wrapper, /recordProgress\?\.\("progress"\)/);
  assert.match(wrapper, /progressUpdate,/);
  assert.match(wrapper, /recordProgress\?\.\(\);/);
  assert.match(await readFile(path.join(sample.directory, 'argos-liveness-patch.json'), 'utf8'), /"upstream_version": "2026\.10\.4"/);
  const once = await readFile(sample.wrapper, 'utf8');
  execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'});
  assert.equal(await readFile(sample.wrapper, 'utf8'), once);

  const runtime = await import(`file://${sample.wrapper.replaceAll('\\', '/')}`);
  const originalNow = Date.now;
  let now = 30001;
  Date.now = () => now;
  try {
    const updates = runtime.makeProgress('argos_evaluate', {aborted:false}, (update) => update);
    updates({content:[{type:'text',text:'first'}]});
    now += 29999;
    updates({content:[{type:'text',text:'too soon'}]});
    now += 2;
    updates({content:[{type:'text',text:'second'}]});
  } finally {
    Date.now = originalNow;
  }
  const progressEvents = runtime.events.filter((event) => event.reason.endsWith(':progress'));
  assert.deepEqual(progressEvents.map((event) => event.reason), [
    'tool:argos_evaluate:progress', 'tool:argos_evaluate:progress'
  ]);
  assert.equal(progressEvents[0].runId, 'fixture-run');
  assert.ok(runtime.events.some((event) => event.reason === 'tool:argos_evaluate:completed'));
});

test('patch refuses unreviewed upstream and ambiguous patch sites', async (t) => {
  const sample = await fixture(t);
  await writeFile(path.join(sample.directory, 'package.json'), JSON.stringify({name:'openclaw', version:'2027.1.0'}));
  assert.throws(() => execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'}));
  await writeFile(path.join(sample.directory, 'package.json'), JSON.stringify({name:'openclaw', version:'2026.10.4'}));
  await writeFile(sample.wrapper, 'unexpected upstream source');
  assert.throws(() => execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'}));
});

test('patch accepts the checksum-reviewed 2026.10.5 source layout', async (t) => {
  const sample = await fixture(t, '2026.10.5');
  execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'});
  assert.match(await readFile(path.join(sample.directory, 'argos-liveness-patch.json'), 'utf8'),
    /"upstream_version": "2026\.10\.5"/);
});
