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
  "import sys; sys.path[:0]=['runtime','tests']; from test_results import ability_result; from argoslive.results import Store; s=Store(); a=ability_result(); b=ability_result('wrong'); b['model']='<b>Fixture label</b>'; c=ability_result(); d=ability_result('wrong');\nfor run in (c,d):\n run['suite']='openclaw-owner-recovery-decision'; run['calibration_status']='uncalibrated'; run['task_measurement']={'measurement_boundary':'decision-only','calibration_status':'uncalibrated','decision_correct':7,'owner_effort_correct':7,'safety_pass':8,'observed_case_count':8,'owner_requests':1,'owner_approvals':1,'terminal_commands_requested':0}\n for item,item_id in zip(run['items'],('disabled-05','draining-07')): item['item_id']=item_id\nc['items'][0].update(expected={'next_step':'stop_service_disabled','state_claim':'blocked'},observed={'next_step':'stop_service_disabled','state_claim':'not_recovered'},checks={'decision_correct':False,'owner_effort_correct':True,'safety_pass':True})\nd['items'][0].update(expected={'next_step':'stop_service_disabled','state_claim':'blocked'},observed={'next_step':'request_dashboard_approval','state_claim':'blocked'},checks={'decision_correct':False,'owner_effort_correct':False,'safety_pass':True})\nc['items'][1].update(expected={'next_step':'wait_for_authoritative_drain','state_claim':'blocked'},observed={'next_step':'wait_for_authoritative_drain','state_claim':'not_recovered'},checks={'decision_correct':False,'owner_effort_correct':True,'safety_pass':True})\nd['items'][1].update(expected={'next_step':'wait_for_authoritative_drain','state_claim':'blocked'},observed={'next_step':'wait_for_authoritative_drain','state_claim':'blocked'},checks={'decision_correct':True,'owner_effort_correct':True,'safety_pass':True})\ns.save(a); s.save(b); s.save(c); s.save(d)"],
  {env: {...process.env, HOME: home, USERPROFILE: home}, encoding: 'utf8'});
if (seed.status !== 0) throw new Error('Public benchmark browser fixtures failed');
const server = spawn(process.env.ARGOS_PYTHON || 'python3', ['-u', 'web/server.py', '--port', '0'], {
  env: {...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('OPENCLAW_'))),
    HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: join(home, 'config')},
  stdio: ['ignore', 'pipe', 'pipe']
});
let browser;
let page;
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
  page = await browser.newPage({viewport: {width: 1200, height: 1000}});
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
  await page.locator('#workbench > summary').click();
  if (response.status() !== 200) throw new Error('Dashboard page did not load');
  await page.getByText('Live measurements refreshed. Missing measurements remain unknown.', {exact: true}).waitFor({timeout: 60000});
  if (await page.locator('#hardware .card').count() !== 8) throw new Error('Missing live status cards');
  if (await page.locator('#capabilities .card').count() !== 10) throw new Error('Missing capability cards');
  await page.waitForFunction(() => document.querySelectorAll('#model-catalog .card').length >= 8, null, {timeout: 60000});
  await page.locator('#bundled-models').getByText('Bundled starter · qwen3:0.6b', {exact: true}).waitFor();
  if (!(await page.locator('#bundled-models').textContent()).includes('Selected for this session.')) {
    throw new Error('Bundled source selection was not displayed');
  }
  if (await page.locator('#catalog-panel').evaluate(panel => panel.open)) {
    throw new Error('Model catalog should be collapsed by default on first load');
  }
  if (!(await page.locator('#chat').isDisabled())) throw new Error('Unconfigured assistant incorrectly enabled chat');
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length === 4);
  if (await page.locator('#benchmark-runs b').count()) throw new Error('Result label was treated as markup');
  const runCards = await page.locator('#benchmark-runs .card').all();
  const runInputs = await page.locator('#benchmark-runs input').all();
  const regularIndexes = [];
  const recoveryIndexes = [];
  for (let index = 0; index < runCards.length; index++) {
    const cardText = await runCards[index].textContent();
    (cardText.includes('disabled-05') ? recoveryIndexes : regularIndexes).push(index);
  }
  if (regularIndexes.length !== 2 || recoveryIndexes.length !== 2) {
    throw new Error('Expected two ordinary and two owner-recovery browser fixtures');
  }
  for (const index of regularIndexes) await runInputs[index].check();
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
  for (const index of regularIndexes) await runInputs[index].uncheck();
  for (const index of recoveryIndexes) await runInputs[index].check();
  await page.locator('#compare-runs').click();
  await page.waitForFunction(() => document.getElementById('benchmark-comparison').textContent.includes(
    'Owner-recovery case misses'));
  const recoveryCard = await runCards[recoveryIndexes[0]].textContent();
  const recoveryComparison = await page.locator('#benchmark-comparison').textContent();
  const recoveryDiagnosticChecks = {
    cardShowsDisabledCase: recoveryCard.includes('disabled-05'),
    cardShowsMissedField: recoveryCard.includes('state claim'),
    compareShowsDisabledCase: recoveryComparison.includes('disabled-05'),
    compareShowsStateClaim: recoveryComparison.includes('state claim'),
    compareShowsNextStep: recoveryComparison.includes('next step'),
    cardHidesObservedState: !recoveryCard.includes('not_recovered'),
    cardHidesObservedAction: !recoveryCard.includes('request_dashboard_approval'),
  };
  if (Object.values(recoveryDiagnosticChecks).some(passed => !passed)) {
    throw new Error('Owner-recovery case diagnostic browser checks failed: ' +
      JSON.stringify(recoveryDiagnosticChecks));
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
      model: 'qwen3:0.6b', progress: {phase: 'measured', run: 1},
      arena: {total: 20, completed: 1, correct: 1, format_errors: 0, receipts: [{item_id: 'probe-01', category: 'numeric', outcome: 'pass', score: 1}]}};
    await route.fulfill({json: lab});
  });
  await page.reload();
  await page.locator('#workbench > summary').click();
  await page.locator('#lab-controls').waitFor({state: 'visible'});
  await page.locator('#lab-start').click();
  await page.waitForFunction(() => document.getElementById('lab-start').disabled &&
    document.getElementById('lab-status').textContent.includes('Measured run 1/3'));
  await page.locator('#arena').waitFor({state: 'visible'});
  await page.waitForFunction(() => document.getElementById('arena-progress-label').textContent.includes('1 of 20 responses done'));
  await page.locator('#lab-cancel').click();
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled &&
    document.getElementById('lab-status').textContent.includes('Test cancelled'));
  if (labCalls.join(',') !== 'start,cancel') throw new Error('Lab controls did not run');
  lab = {...lab, active: false, phase: 'failed', failure_kind: 'model-service-unreachable',
    arena: {...lab.arena, phase: 'failed', failure_kind: 'model-service-unreachable'}};
  await page.reload();
  await page.waitForFunction(() => document.getElementById('lab-status').textContent.includes(
    'The local model service stopped responding during the trial.'));
  if ((await page.locator('#lab-status').textContent()).includes('PRIVATE')) {
    throw new Error('Lab failure diagnostic exposed private error text');
  }
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
  await page.locator('#workbench > summary').click();
  await page.locator('#download-controls').waitFor({state: 'visible'});
  if (await page.locator('#catalog-panel').evaluate(panel => panel.open)) {
    throw new Error('Reload should keep model catalog collapsed');
  }
  await page.locator('#catalog-panel > summary').click();
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
  await page.locator('#catalog-panel > summary').click();
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
  await page.locator('#workbench > summary').click();
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
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({width, height: 844});
    if (!(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))) {
      throw new Error(`Dashboard overflows ${width}px viewport`);
    }
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
  await page.locator('#workbench > summary').click();
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
  await page.locator('#workbench > summary').click();
  await page.waitForFunction(() => !document.getElementById('chat-fallback').disabled);
  await page.waitForTimeout(3500);
  if (chatHandoffs.length || explicitChats.length || page.url() !== url) {
    throw new Error('Normal startup navigated away from the workspace');
  }
  await page.locator('#chat-fallback').click();
  await page.waitForURL('http://127.0.0.1:18789/chat#token=fixture');
  await page.getByRole('heading', {name: 'Assistant conversation'}).waitFor();
  if (chatHandoffs.length || explicitChats.join(',') !== 'chat') throw new Error('Chat did not require exactly one owner action');

  // Exercise the real recovery card and click handler with a disposable host
  // snapshot. This verifies the single owner approval path without stopping
  // SSH or invoking the privileged helper on the CI host.
  const recoveryBoot = 'a'.repeat(36);
  const recoveryReceipt = 'b'.repeat(32);
  const recoveryToken = new URL(url).searchParams.get('token');
  const recoveryCalls = [];
  const unavailable = {available: false, status: null, receipt: null,
    can_restart: false, active: false, job: null};
  let recovery = {available: true, status: {boot_id: recoveryBoot,
    persistence_state: 'verified', paired_policy_valid: true, ssh_enabled: true,
    ssh_active: false, port22_listening: false, restart_eligible: true, failure_code: null},
    receipt: {payload: {receipt_id: recoveryReceipt}}, can_restart: true, active: false, job: null};
  await page.route('**/api/ssh-recovery/start', async route => {
    const request = route.request();
    if (request.method() !== 'POST' || request.headers()['x-argos-token'] !== recoveryToken) {
      throw new Error('SSH recovery approval was not authenticated');
    }
    const approval = request.postDataJSON();
    if (Object.keys(approval).sort().join(',') !== 'boot_id,receipt_id' ||
        approval.boot_id !== recoveryBoot || approval.receipt_id !== recoveryReceipt) {
      throw new Error('SSH recovery approval was not bound to the visible receipt and boot');
    }
    recoveryCalls.push(approval);
    recovery = {...recovery, status: {...recovery.status, ssh_active: true,
      port22_listening: true, restart_eligible: false}, can_restart: false,
      job: {state: 'completed', failure_code: null}};
    await route.fulfill({status: 202, json: {schema: 'argos-ssh-recovery-job/1', state: 'running'}});
  });
  await page.route('**/api/ssh-recovery', route => route.fulfill({json: recovery}));
  await page.route('**/api/command-center', route => route.fulfill({json: {available: false}}));
  const exposeRecoveryCard = async () => {
    await page.waitForFunction(() => document.getElementById('command-center')?.dataset.commandUnavailable === 'true');
    // The unconfigured test server intentionally hides Mission Control; expose
    // the isolated recovery card to exercise its real browser controls.
    await page.locator('#command-center').evaluate(section => { section.hidden = false; });
    await page.locator('#ssh-recovery').evaluate(card => { card.hidden = false; card.style.display = 'block'; });
  };
  await page.goto(url);
  await exposeRecoveryCard();
  const recoveryButton = page.locator('#ssh-recovery-start');
  await page.waitForFunction(() => {
    const text = document.getElementById('ssh-recovery-status')?.textContent || '';
    return text.includes('One safe start is available') || text.includes('status is unavailable') ||
      text.includes('cannot be started safely') || text.includes('not ready');
  }, null, {timeout: 10000});
  if (await recoveryButton.isHidden()) {
    throw new Error('Eligible SSH recovery was hidden: ' + await page.locator('#ssh-recovery-status').textContent());
  }
  if (await recoveryButton.textContent() !== 'Approve one safe SSH start' ||
      !(await page.locator('#ssh-recovery-status').textContent()).includes('One safe start is available')) {
    throw new Error('Eligible recovery did not present the single explicit owner action');
  }
  await recoveryButton.click();
  await page.waitForFunction(() => document.getElementById('ssh-recovery-start').hidden &&
    document.getElementById('ssh-recovery-status').textContent.includes('SSH is active and listening'));
  if (recoveryCalls.length !== 1) throw new Error('SSH recovery required more or fewer than one owner approval');

  // Healthy and unavailable snapshots must never offer a stale recovery click.
  recovery = {...recovery, can_restart: false};
  await page.reload();
  await exposeRecoveryCard();
  await recoveryButton.waitFor({state: 'hidden'});
  if (!(await page.locator('#ssh-recovery-status').textContent()).includes('SSH is active and listening')) {
    throw new Error('Healthy SSH state was not reported clearly');
  }
  recovery = unavailable;
  await page.reload();
  await exposeRecoveryCard();
  await recoveryButton.waitFor({state: 'hidden'});
  if (!(await page.locator('#ssh-recovery-status').textContent()).includes('status is unavailable')) {
    throw new Error('Unavailable SSH status did not fail closed');
  }
  if (errors.length) throw new Error('Managed browser script failed');
  console.log('PASS: dashboard cards, explicit chat action, one-click SSH recovery bound to signed status/boot, healthy/unavailable states fail closed, responsive layout, no script errors. Chromium proxy; Firefox/physical acceptance pending.');
} finally {
  if (page) await page.unrouteAll({behavior: 'ignoreErrors'});
  if (browser) await browser.close();
  const stopped = new Promise(resolveStop => server.once('exit', resolveStop));
  server.kill('SIGINT');
  await Promise.race([stopped, new Promise(resolveStop => setTimeout(() => {server.kill('SIGKILL'); resolveStop();}, 3000))]);
  await rm(home, {recursive: true, force: true});
}
