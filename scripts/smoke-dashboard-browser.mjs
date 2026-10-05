// Real browser check using playwright-core already pinned by the runtime lock.
// Chromium is a CI proxy for Firefox ESR; this is not physical ISO acceptance.
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve('work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');
const home = await mkdtemp(join(tmpdir(), 'argos-dashboard-browser-'));
const seed = spawnSync('python3', ['-c',
  "import sys; sys.path[:0]=['runtime','tests']; from test_results import ability_result; from argoslive.results import Store; s=Store(); a=ability_result(); b=ability_result('wrong'); b['model']='<b>Fixture label</b>'; s.save(a); s.save(b)"],
  {env: {...process.env, HOME: home, USERPROFILE: home}, encoding: 'utf8'});
if (seed.status !== 0) throw new Error('Public benchmark browser fixtures failed');
const server = spawn('python3', ['-u', 'web/server.py', '--port', '0'], {
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
  await page.locator('summary').click();
  if (!(await page.locator('#chat').isDisabled())) throw new Error('Unconfigured assistant incorrectly enabled chat');
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length === 2);
  if (await page.locator('#benchmark-runs b').count()) throw new Error('Result label was treated as markup');
  for (const input of await page.locator('#benchmark-runs input').all()) await input.check();
  await page.locator('#compare-runs').click();
  await page.getByText('Test accuracy: 100.0%', {exact: true}).waitFor();
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
  await page.reload();
  await page.locator('#download-controls').waitFor({state: 'visible'});
  await page.locator('summary').click();
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
  await page.locator('summary').click();
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
  if (errors.length) throw new Error('Managed browser script failed');
  console.log('PASS: live/capability cards, disabled unconfigured chat, refresh, responsive layout, no script errors. Chromium proxy; Firefox/physical acceptance pending.');
} finally {
  if (browser) await browser.close();
  const stopped = new Promise(resolveStop => server.once('exit', resolveStop));
  server.kill('SIGINT');
  await Promise.race([stopped, new Promise(resolveStop => setTimeout(() => {server.kill('SIGKILL'); resolveStop();}, 3000))]);
  await rm(home, {recursive: true, force: true});
}
