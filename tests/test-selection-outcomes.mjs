import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('../runtime/argoslive/web/static/app.js', import.meta.url), 'utf8');
function section(start, end) { return source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))); }
function harness(snap, verifyError = null) {
  const state = {pending: true, verified: 0, status: ''};
  const context = vm.createContext({
    Date, setTimeout,
    api: async () => snap,
    updateModelActionStatus: text => { state.status = text; },
    refreshModels: async () => {}, refreshSelection: async () => {},
    verifyModelSelectionIdentity: async () => { state.verified++; if (verifyError) throw new Error(verifyError); },
    sessionStorage: {removeItem: () => { state.pending = false; }},
    document: {getElementById: () => null}, activeModelMonitoring: null,
  });
  vm.runInContext(section('function selectionOutcome(', 'async function verifyModelSelectionIdentity(') +
    section('async function monitorModelAction(', 'function resumePendingModelMonitoring(') +
    section('async function reconcileModelActionWithController(', 'function renderExperimentRecommendation('), context);
  return {context, state};
}
for (const [phase, expected] of [
  ['idle', 'No model operation confirmed'], ['rolled-back', 'rolled back'],
  ['cancelled', 'Switch cancelled'], ['recovery-blocked', 'recovery blocked'], ['failed', 'Model switch failed'],
]) {
  test(`${phase} is preserved after a lost POST and cannot report success`, async () => {
    const {context, state} = harness({available: true, active: false, phase});
    const primary = {disabled: true}, secondary = {disabled: true};
    await context.reconcileModelActionWithController({actionType: 'switch-candidate', targetModel: 'test', targetDigest: 'digest', startedAt: Date.now()}, null, primary, secondary);
    assert.ok(state.status.includes(expected), state.status);
    assert.equal(state.verified, 0);
    assert.equal(state.pending, false);
    assert.equal(primary.disabled, false);
    assert.equal(secondary.disabled, false);
    assert.ok(!state.status.includes('not started by server'));
    assert.ok(!state.status.includes('switch verified'));
  });
  test(`ordinary polling also rejects ${phase}`, async () => {
    const {context} = harness({available: true, active: false, phase});
    await assert.rejects(context.waitSelectionTerminal(null, 'switch-candidate', Date.now()), error => error.message.includes(expected));
  });
}
test('completed reconciliation requires identity verification', async () => {
  const {context, state} = harness({available: true, active: false, phase: 'completed'});
  await context.reconcileModelActionWithController({actionType: 'switch-candidate', targetModel: 'test', targetDigest: 'digest'}, null, {}, {});
  assert.equal(state.verified, 1);
  assert.ok(state.status.includes('switch verified'));
});
test('completed with wrong identity is refused', async () => {
  const {context, state} = harness({available: true, active: false, phase: 'completed'}, 'Manifest digest mismatch');
  await context.reconcileModelActionWithController({actionType: 'switch-candidate', targetModel: 'test', targetDigest: 'digest'}, null, {}, {});
  assert.ok(state.status.includes('Manifest digest mismatch'));
  assert.ok(!state.status.includes('switch verified'));
});
