import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const packageRoot = path.resolve(process.argv[2] ?? '');
if (!process.argv[2]) throw new Error('Usage: node smoke-evaluation-liveness.mjs OPENCLAW_PACKAGE_ROOT');
const metadata = JSON.parse(await readFile(path.join(packageRoot, 'package.json'), 'utf8'));
if (metadata.name !== 'openclaw' || !['2026.10.4', '2026.10.5', '2026.10.8'].includes(metadata.version))
  throw new Error('Smoke test requires a reviewed OpenClaw 2026.10.4, 2026.10.5, or 2026.10.8 package.');

const dist = path.join(packageRoot, 'dist');
const matches = (await readdir(dist)).filter((name) => /^diagnostic-run-activity-[A-Za-z0-9_-]+\.mjs$/.test(name));
assert.equal(matches.length, 1, 'Expected one pinned diagnostic activity module.');
const eventFiles = (await readdir(dist)).filter((name) => /^diagnostic-events-[A-Za-z0-9_-]+\.mjs$/.test(name));
assert.equal(eventFiles.length, 1, 'Expected one pinned diagnostic event module.');

// The pinned module exposes its activity snapshot API under VITEST. Exercise its
// actual event bus and owner fencing instead of a mock implementation.
process.env.VITEST = '1';
const activity = await import(pathToFileURL(path.join(dist, matches[0])).href);
const events = await import(pathToFileURL(path.join(dist, eventFiles[0])).href);
const now = Date.now;
let clock = now();
Date.now = () => clock;
const params = {runId: 'argos-liveness-run', sessionId: 'argos-liveness-session',
  sessionKey: 'agent:main:argos-liveness'};
let owner;
try {
  activity.m(); // Start the actual pinned diagnostic activity listener.
  owner = activity.i(params);
  activity.u({...params, owner});

  // The prior failure occurred after 903 seconds without activity. Confirm that
  // the tool really ages past that threshold before injecting semantic progress.
  clock += 16 * 60 * 1000;
  const stale = activity.o(params, clock);
  assert.ok(stale.lastProgressAgeMs >= 900_000, 'Fixture must begin beyond the stall threshold.');

  const recordProgress = activity.t({...params, toolName: 'argos_evaluate'});
  assert.equal(typeof recordProgress, 'function', 'Pinned owner must be captured for this run.');
  recordProgress('progress');
  await events.x(); // run.progress is queued by the pinned event dispatcher.
  const refreshed = activity.o(params, clock);
  assert.equal(refreshed.lastProgressReason, 'tool:argos_evaluate:progress');
  assert.equal(refreshed.lastProgressAgeMs, 0,
    'Semantic evaluation progress must refresh the actual pinned liveness clock.');

  console.log(JSON.stringify({schema: 'argos-openclaw-liveness-smoke/1',
    version: metadata.version, stale_progress_age_ms: stale.lastProgressAgeMs,
    refreshed_progress_age_ms: refreshed.lastProgressAgeMs,
    refreshed_reason: refreshed.lastProgressReason}));
} finally {
  if (owner) activity.r(owner);
  activity.h();
  await events.x();
  Date.now = now;
}
