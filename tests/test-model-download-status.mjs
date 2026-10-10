import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('../runtime/argoslive/web/static/app.js', import.meta.url), 'utf8');
const start = source.indexOf('async function refreshModelControls()');
const end = source.indexOf("document.getElementById('download-dismiss')", start);
for (const [phase, active] of [['completed', false], ['interrupted', false], ['downloading', true]]) {
  test(`download controls and status reflect ${phase}`, async () => {
    const elements = new Map();
    const context = vm.createContext({
      downloadRefreshing: false, lastDownloadPhase: null, downloadAvailable: false, downloadActive: false,
      api: async () => ({available: true, active, phase, model: 'reviewed:model'}),
      document: {getElementById: id => {
        if (!elements.has(id)) elements.set(id, {});
        return elements.get(id);
      }},
      refreshModels: async () => {}, byteSize: String,
    });
    vm.runInContext(source.slice(start, end), context);
    await context.refreshModelControls();
    assert.equal(elements.get('download-controls').hidden, !active);
    assert.equal(elements.get('download-pause').disabled, !active);
    assert.equal(elements.get('download-cancel').disabled, !active);
    const text = elements.get('download-status').textContent;
    if (phase === 'completed') {
      assert.match(text, /Downloaded and reply-tested/);
      assert.doesNotMatch(text, /interrupted|unchanged/);
    } else if (phase === 'interrupted') assert.match(text, /Backend interrupted/);
    else assert.match(text, /Downloading model artifacts/);
  });
}
