import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const patcher = path.join(root, 'scripts/patch-openclaw-liveness.mjs');
const activitySource = `function captureDiagnosticToolProgress(event) {
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
const wrapperSource = `\t\t\tconst recordProgress = captureDiagnosticToolProgress(eventBase);
\t\t\trecordToolExecutionStarted(toolCallId, ctx?.runId);
\t\t\tconst args = [
\t\t\t\ttoolCallId,
\t\t\t\texecuteParams,
\t\t\t\tsignal,
\t\t\t\t\t\tonUpdate,
\t\t\t\t\t\t...executionArgs
\t\t\t];
\t\t\tif (terminalDiagnostic.type === "tool.execution.completed" && !signal?.aborted) recordProgress?.();`;

async function fixture(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-openclaw-liveness-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const dist = path.join(directory, 'dist');
  await mkdir(dist);
  await writeFile(path.join(directory, 'package.json'), JSON.stringify({name:'openclaw', version:'2026.10.4'}));
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
});

test('patch refuses unreviewed upstream and ambiguous patch sites', async (t) => {
  const sample = await fixture(t);
  await writeFile(path.join(sample.directory, 'package.json'), JSON.stringify({name:'openclaw', version:'2027.1.0'}));
  assert.throws(() => execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'}));
  await writeFile(path.join(sample.directory, 'package.json'), JSON.stringify({name:'openclaw', version:'2026.10.4'}));
  await writeFile(sample.wrapper, 'unexpected upstream source');
  assert.throws(() => execFileSync(process.execPath, [patcher, sample.directory], {stdio:'pipe'}));
});
