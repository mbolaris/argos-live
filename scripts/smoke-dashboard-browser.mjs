// Real browser check using playwright-core already pinned by the runtime lock.
// Chromium is a CI proxy for Firefox ESR; this is not physical ISO acceptance.
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');
const home = await mkdtemp(join(tmpdir(), 'argos-dashboard-browser-'));
const seed = spawnSync(process.env.ARGOS_PYTHON || 'python3', ['-c',
  "import sys; sys.path[:0]=['runtime','tests']; from test_results import ability_result; from argoslive.results import Store; s=Store(); a=ability_result(); b=ability_result('wrong'); b['model']='<b>Fixture label</b>'; s.save(a); s.save(b)"],
  {env: {...process.env, HOME: home, USERPROFILE: home}, encoding: 'utf8'});
if (seed.status !== 0) throw new Error('Public benchmark browser fixtures failed');
const server = spawn(process.env.ARGOS_PYTHON || 'python3', ['-u', 'web/server.py', '--port', '0'], {
  env: {...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('OPENCLAW_'))),
    HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: join(home, 'config')},
  stdio: ['ignore', 'pipe', 'pipe']
});
let browser;
try {
  const lines = createInterface({input: server.stdout});
  const url = await new Promise((resolveURL, reject) => {
    const deadline = setTimeout(() => reject(new Error('Dashboard startup timed out')), 15000);
    lines.once('line', line => {
      clearTimeout(deadline);
      const match = line.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[A-Za-z0-9_-]+/);
      if (!match) reject(new Error('Dashboard did not provide a session link'));
      else resolveURL(match[0]);
    });
    server.once('error', reject);
  });
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1200, height: 1000}});
  const errors = [];
  page.on('pageerror', () => errors.push('Browser script error'));
  page.on('console', message => { if (message.type() === 'error') errors.push('Browser console error'); });
  // Public display fixture only; no model weights, configuration or readiness
  // claim. Other endpoints still exercise the actual unconfigured server.
  await page.route('**/api/models', async route => {
    const response = await route.fetch();
    const value = await response.json();
    value.bundled = {state: 'available', read_only: true, models: [{tag: 'qwen3:0.6b'}]};
    value.selected_source = 'bundled';
    await route.fulfill({response, json: value});
  });
  const response = await page.goto(url);
  if (response.status() !== 200) throw new Error('Dashboard page did not load');
  await page.getByText('Live measurements refreshed. Missing measurements remain unknown.', {exact: true}).waitFor({timeout: 60000});
  if (await page.locator('#hardware .card').count() !== 8) throw new Error('Missing live status cards');
  if (await page.locator('#capabilities .card').count() !== 10) throw new Error('Missing capability cards');
  await page.waitForFunction(() => document.querySelectorAll('#model-catalog .card').length >= 8, null, {timeout: 60000});
  await page.getByText('Bundled starter · qwen3:0.6b', {exact: true}).waitFor();
  if (!(await page.locator('#bundled-models').textContent()).includes('Selected for this session.')) {
    throw new Error('Bundled source selection was not displayed');
  }
  if (!(await page.locator('#catalog-panel').evaluate(panel => panel.open))) {
    throw new Error('Model catalog should be visible on first load');
  }
  if (!(await page.locator('#chat').isDisabled())) throw new Error('Unconfigured assistant incorrectly enabled chat');
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length === 2);
  if (await page.locator('#benchmark-runs b').count()) throw new Error('Result label was treated as markup');
  for (const input of await page.locator('#benchmark-runs input').all()) await input.check();
  await page.locator('#compare-runs').click();
  // The comparison is a before/after table that keeps accuracy separate from speed.
  await page.getByText('Accuracy and format, shown separately from speed', {exact: true}).waitFor();
  const accuracyRows = await page.locator('#benchmark-comparison table').first().locator('tr').allTextContents();
  if (accuracyRows.length !== 3 || !accuracyRows.some(r => r.includes('100.0%')) || !accuracyRows.some(r => r.includes('0.0%')) ||
      await page.locator('#benchmark-comparison b').count()) {
    throw new Error('Before/after accuracy table was not rendered correctly: ' + JSON.stringify(accuracyRows));
  }
  if (!(await page.locator('#benchmark-comparison').textContent()).includes('Speed and accuracy are separate.')) {
    throw new Error('Comparison did not state that speed and accuracy are separate');
  }
  const csvPending = page.waitForEvent('download');
  await page.locator('#download-comparison').click();
  const csvDownload = await csvPending;
  const csv = await readFile(await csvDownload.path(), 'utf8');
  if (!csv.includes('manifest_digest') || !csv.includes('accuracy')) throw new Error('Comparison CSV failed');
  const jsonPending = page.waitForEvent('download');
  await page.locator('#benchmark-runs button').first().click();
  const jsonDownload = await jsonPending;
  if (JSON.parse(await readFile(await jsonDownload.path(), 'utf8')).kind !== 'ability') throw new Error('Result JSON failed');
  await page.unroute('**/api/models');
  await page.waitForFunction(() => !document.getElementById('refresh').disabled, null, {timeout: 60000});
  await page.locator('#refresh').click();
  await page.locator('#refresh').waitFor({state: 'visible'});
  await page.waitForFunction(() => !document.getElementById('refresh').disabled, null, {timeout: 60000});
  if ((await page.locator('#bundled-models').textContent()).includes('Selected for this session.')) {
    throw new Error('Stale bundled source selection display');
  }
  if (errors.length) throw new Error('Browser script failed');
  let lab = {available: true, active: false, phase: 'idle', runs: []};
  const labCalls = [];
  await page.route('**/api/lab', route => route.fulfill({json: lab}));
  for (const action of ['start', 'cancel']) await page.route('**/api/lab/' + action, async route => {
    if (route.request().method() !== 'POST' || route.request().postData() ||
        route.request().headers()['x-argos-token'] !== new URL(url).searchParams.get('token')) {
      throw new Error('Lab browser control authorization failed');
    }
    labCalls.push(action);
    lab = {...lab, active: action === 'start', phase: action === 'start' ? 'speed' : 'cancelled',
      model: 'qwen3:0.6b', progress: {phase: 'measured', run: 1}};
    await route.fulfill({json: lab});
  });
  await page.reload();
  await page.locator('#lab-controls').waitFor({state: 'visible'});
  await page.locator('#lab-start').click();
  await page.waitForFunction(() => document.getElementById('lab-start').disabled &&
    document.getElementById('lab-status').textContent.includes('Measured run 1/3'));
  await page.locator('#lab-cancel').click();
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled &&
    document.getElementById('lab-status').textContent.includes('Test cancelled'));
  if (labCalls.join(',') !== 'start,cancel') throw new Error('Lab controls did not run');
  let acquisition = {available: true, active: false, phase: 'idle'};
  const modelCalls = [];
  await page.route('**/api/models/control', route => route.fulfill({json: acquisition}));
  await page.route('**/api/models', async route => {
    const response = await route.fetch();
    const value = await response.json();
    value.storage_state = 'available';
    await route.fulfill({response, json: value});
  });
  await page.route('**/api/models/download', async route => {
    if (route.request().method() !== 'POST' ||
        route.request().headers()['x-argos-token'] !== new URL(url).searchParams.get('token')) {
      throw new Error('Download browser authorization failed');
    }
    const choice = route.request().postDataJSON();
    if (Object.keys(choice).join(',') !== 'tag') throw new Error('Unexpected model download input');
    modelCalls.push('download');
    acquisition = {...acquisition, active: true, phase: 'downloading', model: choice.tag,
      progress: {bytes_done: 1048576, bytes_total: 2097152, recent_mib_per_second: 2.5, eta_seconds: 1}};
    await route.fulfill({json: acquisition});
  });
  await page.route('**/api/models/pause', async route => {
    if (route.request().method() !== 'POST' || route.request().postData()) throw new Error('Pause input invalid');
    modelCalls.push('pause');
    acquisition = {...acquisition, active: false, phase: 'paused'};
    await route.fulfill({json: acquisition});
  });
  // Display fixture for storage state; the real server routes and gate are covered by unit and onboarding tests.
  let storageView = {schema: 'argos-storage-view/1', configured: {}, confirmed: false, state: 'available',
    locations: [{label: 'Models', path: '/media/data/ArgosLive/Models/catalog', backing: null, free_bytes: 200 * 2**30,
      total_bytes: 500 * 2**30, reboot: {state: 'not-started'}}],
    candidates: [{id: 'a'.repeat(20), current: true, kind: 'disk', path: '/media/data/ArgosLive/Models/catalog',
      free_bytes: 200 * 2**30, encrypted: false, volume_label: 'DATA', mountpoint: '/media/data', contains_data: false,
      temporary: false}], unused_volumes: [], boot_id_available: true, can_change: true, change_blocked_reason: null};
  const storageCalls = [];
  await page.route('**/api/storage', route => route.fulfill({json: storageView}));
  await page.route('**/api/storage/choose', async route => {
    const request = route.request();
    if (request.method() !== 'POST' || request.headers()['x-argos-token'] !== new URL(url).searchParams.get('token') ||
        Object.keys(request.postDataJSON()).join(',') !== 'candidate') throw new Error('Storage choice authorization failed');
    storageCalls.push(request.postDataJSON().candidate);
    storageView = {...storageView, confirmed: true};
    await route.fulfill({json: {changed: false}});
  });
  await page.reload();
  await page.locator('#download-controls').waitFor({state: 'visible'});
  if (!(await page.locator('#catalog-panel').evaluate(panel => panel.open))) {
    throw new Error('Reload hid the model catalog');
  }
  await page.locator('#model-catalog button').first().click();
  await page.locator('#download-review').waitFor({state: 'visible'});
  if (!(await page.locator('#download-confirm').isDisabled())) throw new Error('Download was allowed before storage was confirmed');
  await page.locator('#download-dismiss').click();
  await page.getByRole('button', {name: 'Confirm this location'}).click();
  await page.locator('#storage-review').waitFor({state: 'visible'});
  await page.locator('#storage-confirm').click();
  await page.waitForFunction(() => document.getElementById('storage-status').textContent.includes('Model location confirmed.'));
  if (storageCalls.join(',') !== 'a'.repeat(20)) throw new Error('Storage choice was not submitted');
  await page.locator('#model-catalog button').first().click();
  await page.locator('#download-review').waitFor({state: 'visible'});
  await page.screenshot({path: 'work/dashboard-download-review.png'});
  if (modelCalls.length) throw new Error('Opening review started a download');
  await page.locator('#download-dismiss').click();
  if (modelCalls.length) throw new Error('Dismissal started a download');
  await page.locator('#model-catalog button').first().click();
  await page.locator('#download-confirm').click();
  await page.waitForFunction(() => document.getElementById('download-status').textContent.includes('2.5 MiB/s'));
  if (!(await page.locator('#lab-start').isDisabled())) throw new Error('Competing lab action enabled');
  await page.locator('#download-pause').click();
  await page.waitForFunction(() => document.getElementById('download-status').textContent.includes('Paused;'));
  if (modelCalls.join(',') !== 'download,pause') throw new Error('Guided download controls failed');
  await page.locator('details:has(#model-catalog) > summary').click();
  await page.locator('section:has(#models-title)').screenshot({path: 'work/dashboard-download-progress.png'});
  let selection = {available: true, active: false, phase: 'idle'};
  const selectionCalls = [];
  await page.route('**/api/models/selection', route => route.fulfill({json: selection}));
  await page.route('**/api/models', async route => {
    const response = await route.fetch(); const value = await response.json();
    value.storage_state = 'available'; value.selected_model = 'qwen3:0.6b'; value.selected_source = 'bundled';
    value.bundled = {state: 'available', models: [{tag: 'qwen3:0.6b'}]};
    value.installed = [{tag: 'qwen3:4b', files_present: true, catalog_manifest_match: true}];
    await route.fulfill({response, json: value});
  });
  await page.route('**/api/models/select', async route => {
    if (route.request().method() !== 'POST' || route.request().headers()['x-argos-token'] !== new URL(url).searchParams.get('token') ||
        route.request().postDataJSON().tag !== 'qwen3:4b') throw new Error('Selection input invalid');
    selectionCalls.push('select'); selection = {...selection, active: true, phase: 'starting'};
    await route.fulfill({json: selection});
  });
  await page.route('**/api/models/select-cancel', async route => {
    selectionCalls.push('cancel'); selection = {...selection, active: false, phase: 'cancelled'};
    await route.fulfill({json: selection});
  });
  await page.reload();
  await page.locator('#installed-models button').waitFor();
  if (await page.locator('#selection-controls').isVisible() || await page.locator('#selection-cancel').isVisible()) {
    throw new Error('Idle selection displays an operation or cancellation control');
  }
  await page.locator('#installed-models button').click();
  await page.locator('#selection-review').waitFor({state: 'visible'});
  await page.screenshot({path: 'work/dashboard-selection-review.png'});
  if (selectionCalls.length) throw new Error('Review switched model');
  await page.locator('#selection-dismiss').click();
  if (selectionCalls.length) throw new Error('Dismiss switched model');
  await page.locator('#installed-models button').click();
  await page.locator('#selection-confirm').click();
  await page.waitForFunction(() => document.getElementById('selection-status').textContent.includes('Testing the selected'));
  if (!(await page.locator('#lab-start').isDisabled())) throw new Error('Selection did not exclude benchmark');
  await page.locator('#selection-cancel').click();
  await page.waitForFunction(() => document.getElementById('selection-status').textContent.includes('Switch cancelled'));
  if (await page.locator('#selection-cancel').isVisible()) throw new Error('Completed cancellation still offers cancel');
  if (selectionCalls.join(',') !== 'select,cancel') throw new Error('Selection controls failed');
  await page.screenshot({path: 'work/dashboard-desktop.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  if (!(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))) {
    throw new Error('Dashboard overflows narrow viewport');
  }
  await page.screenshot({path: 'work/dashboard-narrow.png', fullPage: true});
  // Managed controls use an authored display fixture. Actual native services
  // and measured warmup are exercised separately by smoke-desktop-startup.py.
  let startup = {schema: 'argos-startup/1', managed: true, phase: 'first-reply',
    message: 'Warming up the local model…', active: true, can_start: false, can_stop: true,
    elapsed_seconds: 2, model_reply_verified: false, metrics: null, auto_open_chat: false};
  const controlCalls = [];
  await page.route('**/api/startup', route => route.fulfill({json: startup}));
  for (const action of ['start', 'stop']) await page.route('**/api/startup/' + action, async route => {
    if (route.request().method() !== 'POST' ||
        route.request().headers()['x-argos-token'] !== new URL(url).searchParams.get('token') ||
        route.request().postData()) throw new Error('Managed browser control authorization failed');
    controlCalls.push(action);
    startup = {...startup, phase: action === 'stop' ? 'stopped' : 'first-reply',
      message: action === 'stop' ? 'Your assistant is stopped.' : 'Warming up the local model…',
      can_start: action === 'stop', can_stop: action === 'start'};
    await route.fulfill({json: startup});
  });
  await page.reload();
  await page.locator('#startup-controls').waitFor({state: 'visible'});
  if (!(await page.locator('#start-assistant').isDisabled()) || await page.locator('#stop-assistant').isDisabled()) {
    throw new Error('Managed warmup controls are incorrect');
  }
  await page.locator('#stop-assistant').click();
  await page.waitForFunction(() => !document.getElementById('start-assistant').disabled);
  await page.locator('#start-assistant').click();
  await page.waitForFunction(() => document.getElementById('start-assistant').disabled);
  if (controlCalls.join(',') !== 'stop,start') throw new Error('Managed browser controls did not run');
  startup = {...startup, model_reply_verified: true, metrics: {backend: {mode: 'CPU'},
    generation_tokens_per_second: 4, time_to_first_token_seconds: .25}};
  await page.waitForFunction(() => document.getElementById('startup-metrics').textContent.includes('4.0 tokens/s'));
  if (!(await page.locator('#startup-metrics').textContent()).includes('First token 0.25 s')) {
    throw new Error('Measured warmup display is missing');
  }
  await page.setViewportSize({width: 1200, height: 1000});
  await page.screenshot({path: 'work/dashboard-startup.png', fullPage: true});
  // Both menu and ordinary startup keep the workspace visible. Even a stale
  // auto_open_chat flag must not navigate; conversation requires an owner click.
  startup = {...startup, phase: 'ready', message: 'Your local assistant is ready.', elapsed_seconds: 60,
    active: false, can_start: false, can_stop: false, auto_open_chat: true, model_reply_verified: true};
  const chatHandoffs = [];
  await page.route('**/api/startup/chat', async route => {
    if (route.request().method() !== 'POST' || route.request().postData() ||
        route.request().headers()['x-argos-token'] !== new URL(url).searchParams.get('token')) {
      throw new Error('Automatic chat handoff authorization failed');
    }
    chatHandoffs.push('chat');
    await route.fulfill({json: {url: 'http://127.0.0.1:18789/chat#token=fixture'}});
  });
  await page.route('http://127.0.0.1:18789/chat', route =>
    route.fulfill({contentType: 'text/html', body: '<title>Chat fixture</title><h1>Assistant conversation</h1>'}));
  await page.route('**/api/status', async route => {
    const response = await route.fetch(); const value = await response.json();
    await route.fulfill({response, json: {...value, assistant: 'ready', chat_available: true}});
  });
  const explicitChats = [];
  await page.route('**/api/assistant/chat', async route => {
    if (route.request().method() !== 'GET' ||
        route.request().headers()['x-argos-token'] !== new URL(url).searchParams.get('token')) {
      throw new Error('Explicit chat action authorization failed');
    }
    explicitChats.push('chat');
    await route.fulfill({json: {url: 'http://127.0.0.1:18789/chat#token=fixture'}});
  });
  await page.goto(url + '&view=lab#benchmarks-title');
  await page.getByRole('heading', {name: 'Detailed test records'}).waitFor();
  await page.locator('#lab-controls').waitFor({state: 'visible'});
  await page.getByText('Live measurements refreshed. Missing measurements remain unknown.', {exact: true}).waitFor();
  await page.waitForTimeout(3500);
  if (chatHandoffs.length || new URL(page.url()).searchParams.get('view') !== 'lab') {
    throw new Error('Model lab view was redirected into chat');
  }
  await page.screenshot({path: 'work/dashboard-model-lab.png', fullPage: true});
  await page.goto(url);
  await page.waitForFunction(() => !document.getElementById('chat-fallback').disabled);
  await page.waitForTimeout(3500);
  if (chatHandoffs.length || explicitChats.length || page.url() !== url) {
    throw new Error('Normal startup navigated away from the workspace');
  }
  await page.locator('#chat-fallback').click();
  await page.waitForURL('http://127.0.0.1:18789/chat#token=fixture');
  await page.getByRole('heading', {name: 'Assistant conversation'}).waitFor();
  if (chatHandoffs.length || explicitChats.join(',') !== 'chat') throw new Error('Chat did not require exactly one owner action');
  if (errors.length) throw new Error('Managed browser script failed');
  console.log('PASS: live/capability cards, catalog visible, idle cancel hidden, workspace stays open until explicit chat action, responsive layout, no script errors. Chromium proxy; Firefox/physical acceptance pending.');
} finally {
  if (browser) await browser.close();
  const stopped = new Promise(resolveStop => server.once('exit', resolveStop));
  server.kill('SIGINT');
  await Promise.race([stopped, new Promise(resolveStop => setTimeout(() => {server.kill('SIGKILL'); resolveStop();}, 3000))]);
  await rm(home, {recursive: true, force: true});
}
