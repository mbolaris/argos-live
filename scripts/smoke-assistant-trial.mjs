// U10 acceptance in the browser: one GO approves a capped multi-idea matched session,
// followed by a fixture-assistant opinion, chained Keep/Restore, and diagnostic routing.
// Fixture replies only; never real-model evidence.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const {chromium} = require('playwright-core');
const server = spawn(process.env.ARGOS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-u', 'scripts/serve-journey-fixture.py'],
  {stdio: ['pipe', 'pipe', 'inherit'], env: {...process.env, ARGOS_FIXTURE_STREAM_DELAY: '0.02'}});
let browser;
try {
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture timeout')), 25000);
    createInterface({input: server.stdout}).once('line', line => { clearTimeout(timer); done(line.trim()); });
    server.once('error', reject);
  });
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(`console: ${message.text()}`); });
  await page.route('**/style.css?*', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + '\n.simulation-banner{position:fixed;bottom:0;left:0;right:0;z-index:10000;background:#453329;color:#ffe2b0;text-align:center;font:11px system-ui;padding:5px}'});
  });
  await mkdir('output/playwright/assistant-trial', {recursive: true});
  const shot = async (name, target = '#assistant-trial') => {
    await page.evaluate(() => {
      if (!document.querySelector('.simulation-banner')) {
        const banner = document.createElement('div'); banner.className = 'simulation-banner';
        banner.textContent = 'SIMULATED PREVIEW · FIXTURE ASSISTANT REPLIES · NOT A REAL MODEL';
        document.body.prepend(banner);
      }
      // A native modal is above the body watermark in the top layer.
      const modal = document.querySelector('dialog[open]');
      if (modal) {
        const badge = document.createElement('div'); badge.className = 'fixture-modal-label';
        badge.style.cssText = 'position:absolute;top:0;left:0;right:0;background:#453329;color:#ffe2b0;text-align:center;font:11px system-ui;padding:4px';
        badge.textContent = 'SIMULATED'; modal.prepend(badge);
      }
    });
    for (const [suffix, width, height] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
      await page.setViewportSize({width, height});
      await page.evaluate(selector => { const el = document.querySelector(selector); scrollTo(0, el.getBoundingClientRect().top + scrollY - 12); }, target);
      if (width === 390 && name === '1-offer') {
        const go = page.locator('#cc-next-go');
        assert.equal(await go.evaluate(el => getComputedStyle(el).position), 'fixed', 'GO stays in reach while reviewing the plan on a phone');
        const box = await go.boundingBox();
        assert.ok(box.y + box.height <= 820, 'The pinned GO sits above the simulated-preview banner');
      }
      if (width === 390 && ['4-result', '4-result-one-gain-restore', '5-kept'].includes(name)) {
        const action = page.locator('#assistant-trial .assistant-trial-actions > .mission-primary:visible');
        assert.equal(await action.count(), 1, 'The phone has one prominent next action');
        assert.equal(await action.evaluate(el => getComputedStyle(el).position), 'fixed', 'The result decision stays in reach on a phone');
        const box = await action.boundingBox();
        assert.ok(box.y + box.height <= 820, 'The pinned decision sits above the simulated-preview banner');
      }
      await page.screenshot({path: `output/playwright/assistant-trial/${name}-${suffix}.png`});
    }
    if (['1-offer', '4-result', '4-result-one-gain-restore', '5-kept'].includes(name)) {
      await page.setViewportSize({width: 320, height: 720});
      await page.evaluate(selector => { const el = document.querySelector(selector); scrollTo(0, el.getBoundingClientRect().top + scrollY - 12); }, target);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= 320), 'The 320px phone layout has no horizontal overflow');
      const action = name === '1-offer' ? page.locator('#cc-next-go') :
        page.locator('#assistant-trial .assistant-trial-actions > .mission-primary:visible');
      assert.equal(await action.evaluate(el => getComputedStyle(el).position), 'fixed', 'The single next action stays pinned on a narrow phone');
      const box = await action.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= 320 && box.y + box.height <= 696,
        'The narrow-phone action fits above the simulated-preview banner');
    }
    await page.setViewportSize({width: 1280, height: 900});
    await page.locator('.fixture-modal-label').evaluateAll(nodes => nodes.forEach(node => node.remove()));
  };
  const status = () => page.evaluate(() => api('/api/assistant-trial'));
  await page.goto(url);
  await page.locator('#cc-next-go').waitFor({state: 'visible'});
  assert.equal(await page.locator('#cc-next-go').getAttribute('data-action'), 'documents',
    'The first GO starts the required foundation mission');
  await page.locator('#cc-next-go').click();
  await page.waitForFunction(() => !document.getElementById('cc-receipt').hidden &&
    document.getElementById('command-center').dataset.watching === 'false', null, {timeout: 60000});
  await page.waitForFunction(() => document.getElementById('cc-next-go').dataset.action === 'assistant-trial' &&
    !document.getElementById('cc-next-trial-offer').hidden, null, {timeout: 10000});
  assert.equal(await page.locator('#cc-next-label').textContent(), 'Your next move');
  assert.equal(await page.locator('#cc-receipt').isVisible(), true, 'The starting mission result remains visible before GO');
  assert.equal(await page.locator('#replay').isHidden(), true, 'Detailed replay is tucked away while the next move is in focus');
  assert.equal(await page.locator('#command-center').getAttribute('data-watching'), 'false');
  assert.equal((await status()).status, 'none');

  // Simulate an unrelated storage blocker after the foundation mission. The
  // real-model improvement loop should still be the obvious next GO.
  const completedCommand = await page.evaluate(() => api('/api/command-center'));
  completedCommand.next_action = {id: 'storage', title: 'Choose model storage', reason: 'Storage is not configured.', action: 'storage'};
  await page.route('**/api/command-center', route => route.fulfill({json: completedCommand}));
  await page.evaluate(() => refreshCommand());
  await page.waitForFunction(() => document.getElementById('cc-next-go').dataset.action === 'assistant-trial' &&
    !document.getElementById('cc-next-trial-offer').hidden, null, {timeout: 10000});
  assert.equal(await page.locator('#cc-next-title').textContent(), 'Find your AI’s next improvement');
  assert.equal(await page.locator('#cc-next-go').getAttribute('aria-label'), 'Start improvement round');
  assert.equal(await page.locator('.cc-hero-actions #chat').count(), 0, 'Chat is separate from the primary action');
  assert.equal(await page.locator('.cc-chat-area #chat').textContent(), 'Open chat ↗');
  assert.match(await page.locator('#cc-next-reason').textContent(), /Same model\. Same eight challenges/);
  assert.equal(await page.locator('#cc-next-trial-offer').isVisible(), true);
  assert.match(await page.locator('#cc-next-trial-offer').textContent(), /3 ideas · 8 challenges each/i);
  assert.match(await page.locator('#cc-next-trial-offer').textContent(), /up to 32 model replies/i);
  assert.equal(await page.locator('#workbench > summary').isVisible(), true,
    'Model and storage setup remains accessible as a separate optional path');
  assert.equal(await page.locator('#cc-next-trial-ideas-details').evaluate(el => el.open), false,
    'The exact instruction cards stay tucked away until the user asks to inspect them');
  assert.equal(await page.locator('#cc-next-trial-instructions .cc-next-trial-idea').count(), 3);
  await page.locator('#cc-next-trial-ideas-summary').click();
  assert.match(await page.locator('#cc-next-trial-instructions').textContent(), /Answer first/);
  assert.match(await page.locator('#cc-next-trial-instructions').textContent(), /Show the source/);
  assert.match(await page.locator('#cc-next-trial-instructions').textContent(), /Be honest when the source is silent/);
  assert.equal(await page.locator('#cc-next-trial-instructions details').count(), 3);
  await page.locator('#cc-next-trial-instructions details').first().locator('summary').click();
  assert.match(await page.locator('#cc-next-trial-instructions details').first().textContent(), /begin with the direct answer in one short sentence/,
    'The exact approved instruction remains available before GO');
  await page.locator('#cc-next-trial-instructions details').first().locator('summary').click();
  await page.locator('#cc-next-trial-ideas-summary').click();
  await page.evaluate(async () => {
    assistantTrial = {...assistantTrial, first_run_setup: true};
    await refreshCommand();
  });
  assert.equal(await page.locator('#cc-next-trial-first-run').isVisible(), true);
  assert.match(await page.locator('#cc-next-trial-first-run').textContent(), /pinned OpenClaw defaults/i);
  assert.equal(await page.locator('#arena').isHidden(), true, 'The previous mission is tucked away during the focused offer');
  assert.equal(await page.locator('#chat').isHidden(), true, 'GO is the only primary action for this offer');
  await shot('1-offer', '#cc-next');

  // The owner may press GO while the assistant is still warming. This state
  // is a deterministic UI fixture, not evidence of model inference.
  await page.evaluate(() => {
    trialFollow = true;
    assistantTrial = {...assistantTrial, active: true, phase: 'preparing', progress: null,
      status: 'none', result_state: 'none', result: null, max_answers: 32,
      message: 'Warming up your local assistant. No instructions have changed.'};
    renderAssistantTrial();
  });
  assert.equal(await page.locator('#assistant-trial-title').textContent(), 'Warming up your AI');
  assert.match(await page.locator('#assistant-trial-text').textContent(), /GO is queued.*no idea has been applied/i);
  assert.equal(await page.locator('#assistant-trial-stage').textContent(), 'Warming up your local AI');
  assert.equal(await page.locator('#assistant-trial-count').textContent(), '0 of 32 model replies');
  assert.equal(await page.locator('#assistant-trial-question').textContent(), 'Your GO is saved. The assistant will begin when it’s ready.');
  assert.equal(await page.locator('#assistant-trial-cancel').textContent(), 'Cancel warm-up');
  assert.equal(await page.locator('#assistant-trial-note').isHidden(), true,
    'The warm-up explanation appears once, without a duplicate status note');
  await shot('1-warming-up');
  await page.evaluate(() => {
    assistantTrial = {...assistantTrial, phase: 'workspace', progress: {side: 'before', done: 0, total: 8,
      current: {kind: 'setup', question: 'One quick private setup check before scoring.'}, latest: null,
      session_done: 0, session_total: 32, waiting_seconds: 7},
      message: 'Setting up only missing standard starter files from the pinned OpenClaw defaults. Existing files will not be overwritten. No challenge is scored yet.'};
    renderAssistantTrial();
  });
  assert.equal(await page.locator('#assistant-trial-title').textContent(), 'Getting your AI ready');
  assert.equal(await page.locator('#assistant-trial-stage').textContent(), 'First-run setup · no score yet');
  assert.match(await page.locator('#assistant-trial-text').textContent(), /only missing standard starter files/i);
  assert.equal(await page.locator('#assistant-trial-count').textContent(), '0 of 32 model replies');
  assert.match(await page.locator('#assistant-trial-thinking').textContent(), /7s · adding only missing starter files/i);
  assert.equal(await page.locator('#assistant-trial-cancel').textContent(), 'Cancel setup');
  await shot('1-first-run-setup');
  await page.evaluate(async () => { trialFollow = false; await refreshAssistantTrial(); });
  await page.waitForFunction(() => document.getElementById('assistant-trial-title').textContent !== 'Warming up your AI');
  await page.unroute('**/api/command-center');

  // A completed document result should lead to one safe improvement offer,
  // independent of storage/model next actions; the disclosed GO is approval.
  const firstMission = await page.evaluate(() => presentedNextAction(
    {id: 'documents', title: 'Read this brief', reason: 'Read eight passages.', action: 'documents'}, assistantTrial, null));
  assert.equal(firstMission.action, 'documents', 'An empty build still starts its foundation mission first');
  const guidedAction = await page.evaluate(() => presentedNextAction(
    {id: 'review', title: 'See why answers missed', reason: 'Inspect diagnostics.', action: 'review'}, assistantTrial, null));
  assert.equal(guidedAction.action, 'assistant-trial');
  assert.equal(guidedAction.title, 'Find your AI’s next improvement');
  assert.match(guidedAction.reason, /Same model\. Same eight challenges/);
  const afterDocumentStorageAction = await page.evaluate(() => presentedNextAction(
    {id: 'storage', title: 'Choose model storage', reason: 'Storage is not configured.', action: 'storage'},
    {available: true, status: 'none', changes: [{id: 'answer-first'}, {id: 'quote-evidence'}]},
    {ability: {suite: 'documents-short', qualified: false}}));
  assert.equal(afterDocumentStorageAction.action, 'assistant-trial',
    'A completed document result can start the assistant trial without configuring download storage');
  assert.match(afterDocumentStorageAction.reason, /Same model\. Same eight challenges/);
  const busyAction = await page.evaluate(() => presentedNextAction(
    {id: 'wait', title: 'A task is running', reason: 'Chat resumes when it finishes.', action: null},
    {available: true, status: 'none', changes: [{id: 'answer-first'}]},
    {ability: {suite: 'documents-short', qualified: false}}));
  assert.equal(busyAction.action, null, 'A running workload keeps its wait state instead of offering another run');
  const restoreAction = await page.evaluate(() => presentedNextAction(
    {id: 'restore', title: 'Restore the model that met the standard', reason: 'This model missed.', action: 'restore'},
    {available: true, status: 'none', changes: [{id: 'answer-first'}]},
    {ability: {suite: 'documents-short', qualified: false}}));
  assert.equal(restoreAction.action, 'restore', 'A safety recovery recommendation keeps priority over improvement');
  const runningAction = await page.evaluate(() => presentedNextAction(
    {id: 'review', title: 'Review', reason: 'Review.', action: 'review'}, {available: true, status: 'none', active: true}));
  assert.equal(runningAction.title, 'Watch the improvement run');
  const blockedAction = await page.evaluate(() => presentedNextAction(
    {id: 'review', title: 'Review', reason: 'Review.', action: 'review'},
    {available: true, status: 'none', result_state: 'recovery-blocked', message: 'Review the workspace.'}));
  assert.equal(blockedAction.action, null, 'A safety stop does not offer another blind GO');
  const savedTrialState = await page.evaluate(() => structuredClone(assistantTrial));
  const receiptWasHidden = await page.locator('#cc-receipt').isHidden();
  const offerWasDismissed = await page.evaluate(() => assistantTrialOfferDismissed);
  await page.evaluate(() => {
    assistantTrialOfferDismissed = true;
    document.getElementById('cc-receipt').hidden = false;
    assistantTrial = {...assistantTrial, available: true, active: false, status: 'none',
      phase: 'recovery-blocked', result_state: 'recovery-blocked', result: null,
      message: 'The first reply changed files in the AI’s workspace. No score was counted and no experiment was applied; the assistant is stopped until you review those files.'};
    renderAssistantTrial();
  });
  assert.equal(await page.locator('#assistant-trial').isVisible(), true,
    'The terminal safety state is visible instead of leaving the user at a spinner or GO button');
  assert.equal(await page.locator('#cc-next').isHidden(), true,
    'A terminal stop takes focus instead of competing with another GO action');
  assert.equal(await page.locator('#assistant-trial-title').textContent(), 'Safety stop — review the workspace');
  assert.match(await page.locator('#assistant-trial-text').textContent(), /No score was counted/);
  assert.equal(await page.locator('.assistant-trial-actions').isHidden(), true);
  assert.equal(await page.locator('#assistant-trial-plan').isHidden(), true);
  assert.equal(await page.locator('#assistant-trial-progress').isHidden(), true);
  await shot('1-safety-stop');
  await page.evaluate(({value, wasHidden, wasOfferDismissed}) => {
    assistantTrial = value;
    assistantTrialOfferDismissed = wasOfferDismissed;
    document.getElementById('cc-receipt').hidden = wasHidden;
    renderAssistantTrial();
  }, {value: savedTrialState, wasHidden: receiptWasHidden, wasOfferDismissed: offerWasDismissed});
  const decisionAction = await page.evaluate(() => presentedNextAction(
    {id: 'review', title: 'Review', reason: 'Review.', action: 'review'}, {available: true, status: 'on-trial', active: false}));
  assert.equal(decisionAction.title, 'Choose what stays in your assistant');
  const keptAction = await page.evaluate(() => presentedNextAction(
    {id: 'review', title: 'Review', reason: 'Review.', action: 'review'}, {available: true, status: 'kept', active: false,
      changes: [{id: 'answer-first'}]}));
  assert.equal(keptAction.action, 'assistant-trial');
  assert.equal(await page.locator('#cc-next-go').getAttribute('aria-label'), 'Start improvement round');
  await page.locator('#cc-next-go').click();
  await page.waitForFunction(async () => (await api('/api/assistant-trial')).active, null, {timeout: 10000, polling: 100});
  assert.equal(await page.locator('#assistant-trial-modal').count(), 0, 'The one GO action starts the exact disclosed trial; no second approval dialog');
  await shot('2-one-go-running');

  // ---- One GO runs baseline, temporary change, matched retest and opinion.
  await page.waitForFunction(() => !document.getElementById('assistant-trial-progress').hidden &&
    document.getElementById('assistant-trial-stage').textContent.startsWith('Starting setup'), null, {timeout: 10000});
  assert.equal(await page.locator('#cc-next').isHidden(), true,
    'The main mission card does not compete with the running trial');
  for (const id of ['#cc-receipt-kicker', '#cc-receipt-title', '#cc-takeaway', '#improve-comparison', '#cc-debrief', '#full-skill-map']) {
    assert.equal(await page.locator(id).isHidden(), true,
      `${id} is tucked away while the assistant trial is in focus`);
  }
  await page.waitForFunction(() => !document.getElementById('assistant-trial-latest').hidden, null, {timeout: 10000});
  assert.match(await page.locator('#assistant-trial-count').textContent(), /[1-8] of 32 model replies/);
  assert.equal(await page.locator('#assistant-trial-title').textContent(), 'I’m proving my next improvement');
  assert.match(await page.locator('#assistant-trial-text').textContent(), /same challenges/i);
  assert.ok((await page.locator('#assistant-trial-question').textContent()).length > 10);
  assert.ok((await page.locator('#assistant-trial-last-question').textContent()).length > 10,
    'The visible answer is paired with the challenge that produced it');
  assert.ok((await page.locator('#assistant-trial-reply').textContent()).length > 5);
  assert.ok(await page.locator('#assistant-trial-checks li').count() > 0);
  assert.equal(await page.locator('#assistant-trial-pips span').count(), 8);
  assert.equal(await page.locator('#assistant-trial-source').isHidden(), false, 'The current document source is available while watching');
  await page.setViewportSize({width: 390, height: 844});
  const stopBox = await page.locator('#assistant-trial-cancel').boundingBox();
  assert.equal(await page.locator('#assistant-trial-cancel').evaluate(el => getComputedStyle(el).position), 'static',
    'Stop stays in the progress header instead of covering the live answer on a phone');
  const questionBox = await page.locator('#assistant-trial-question').boundingBox();
  assert.ok(stopBox.y + stopBox.height <= questionBox.y,
    'The phone Stop control stays above the challenge and answer');
  assert.equal(await page.locator('#assistant-trial-cancel').evaluate(el => el.parentElement.classList.contains('trial-watch-topline')), true,
    'Stop sits beside live progress');
  assert.ok(stopBox.width <= 140, `The phone Stop control stays close to its label (actual width ${stopBox.width}px)`);
  await page.setViewportSize({width: 1280, height: 900});
  const desktopStopBox = await page.locator('#assistant-trial-cancel').boundingBox();
  assert.ok(desktopStopBox.width <= 140, 'On desktop, Stop is a compact control instead of a full-width bar');
  await shot('3-running');
  try {
    await page.waitForFunction(async () => {
      const value = await api('/api/assistant-trial');
      return !value.active && value.status === 'on-trial';
    }, null, {timeout: 60000, polling: 500});
  } catch (error) {
    console.error('The first assistant trial did not reach its decision:', JSON.stringify({trial: await status(), errors}));
    await page.screenshot({path: 'output/playwright/assistant-trial/first-trial-timeout.png', fullPage: true});
    throw error;
  }
  try {
    await page.waitForFunction(() => !document.getElementById('assistant-trial-result').hidden, null, {timeout: 10000});
  } catch (error) {
    const state = await page.evaluate(async () => ({
      rendered: {status: assistantTrial?.status, active: assistantTrial?.active, hasResult: Boolean(assistantTrial?.result),
        resultState: assistantTrial?.result_state, actionPending: trialActionPending, followScheduled: Boolean(trialFollow)},
      resultHidden: document.getElementById('assistant-trial-result').hidden,
      server: await api('/api/assistant-trial'),
    }));
    console.error('Server completed the run but the result card stayed hidden:', JSON.stringify(state));
    throw error;
  }
  const result = (await status()).result;
  assert.equal(result.experiments.length, 3);
  assert.equal(result.selected_change, 'quote-evidence');
  assert.deepEqual(result.totals, {answer: {before: 0, after: 3, total: 3}, not_stated: {before: 0, after: 0, total: 3},
                                   control: {before: 2, after: 2, total: 2}}, JSON.stringify(result.rows.map(row => ({id: row.id, before: row.before.reply, after: row.after.reply}))));
  assert.equal(result.evidence, 'everyday-assistant');
  const card = await page.locator('#assistant-trial').textContent();
  assert.equal(await page.locator('#assistant-trial-result .assistant-trial-verdict h5').textContent(), 'Better on this retest');
  assert.match(card, /3 of 8 challenges improved · 5 stayed the same · 0 slipped/);
  assert.match(card, /Answer first/);
  assert.match(card, /Show the source/);
  assert.match(card, /Recommended next: keep this change/);
  assert.match(card, /not meaningful/);
  assert.equal(await page.locator('#assistant-trial-opinion').isVisible(), true,
    'The same run ends with the local fixture assistant’s separate opinion');
  assert.match(await page.locator('#assistant-trial-opinion-text').textContent(), /I handled the supplied notices better/);
  assert.match(await page.locator('#assistant-trial-opinion').textContent(), /not scored/);
  assert.match(await page.locator('#assistant-trial-opinion-model').textContent(), /no tools or personal profile loaded/);
  assert.doesNotMatch(await page.locator('#assistant-trial-opinion').textContent(), /\d+ of 32/,
    'No session-wide lab count is presented as an assistant score');
  assert.equal(await page.locator('#assistant-trial-keep').isVisible(), true);
  assert.equal(await page.locator('#assistant-trial-keep').textContent(), 'Keep “Show the source” · recommended');
  assert.equal(await page.locator('#assistant-trial .assistant-trial-checkpoint').count(), 8,
    'The result shows one visual checkpoint for each matched challenge');
  assert.equal(await page.locator('#receipt-actions').isHidden(), true,
    'The completed assistant trial owns the next step instead of competing lab options');
  assert.equal(await page.locator('#receipt-extra-details').isHidden(), true,
    'Unrelated scores and skill records stay out of the active decision view');
  assert.equal(await page.locator('#cc-next').isHidden(), true,
    'The main GO card stays out of the Keep/Restore decision');
  for (const id of ['#cc-receipt-kicker', '#cc-receipt-title', '#cc-takeaway', '#improve-comparison', '#cc-debrief',
                    '#cc-strengths-disclosure', '#cc-evidence-disclosure', '#cc-diagnostics-disclosure',
                    '#example-missions', '#cc-progress-journal', '#cc-task-box', '#full-skill-map']) {
    assert.equal(await page.locator(id).isHidden(), true,
      `${id} stays out of the active decision view`);
  }
  assert.deepEqual((await page.locator('#assistant-trial .assistant-trial-actions button:visible').allTextContents()),
    ['Keep “Show the source” · recommended'], 'Only the recommended action is prominent');
  assert.equal(await page.locator('#assistant-trial-alternatives').isVisible(), true);
  assert.equal(await page.locator('#assistant-trial-restore').isVisible(), false,
    'The alternative is tucked under one choice disclosure');
  await page.locator('#assistant-trial-alternatives > summary').click();
  assert.equal(await page.locator('#assistant-trial-restore').isVisible(), true,
    'The alternate outcome remains available');
  await page.locator('#assistant-trial-alternatives > summary').click();
  await page.locator('#assistant-trial-score-details > summary').click();
  await page.evaluate(() => refreshAssistantTrial());
  assert.equal(await page.locator('#assistant-trial-score-details').evaluate(el => el.open), true,
    'Polling preserves opened per-question evidence');
  await page.locator('#assistant-trial-score-details > summary').click();
  await shot('4-result');

  // Exercise the cautious, one-gain result that needs a clear Restore recommendation.
  const oneGain = structuredClone(result);
  oneGain.gains = oneGain.gains.slice(0, 1);
  oneGain.regressions = [];
  oneGain.suggestion = 'restore';
  oneGain.totals = {answer: {before: 0, after: 0, total: 3}, not_stated: {before: 2, after: 3, total: 3},
                    control: {before: 2, after: 2, total: 2}};
  let forcedTrialResult = oneGain;
  await page.route('**/api/assistant-trial', async route => {
    const response = await route.fetch();
    const payload = await response.json();
    if (forcedTrialResult) payload.result = forcedTrialResult;
    await route.fulfill({response, body: JSON.stringify(payload)});
  });
  await page.evaluate(() => refreshAssistantTrial());
  assert.equal(await page.locator('#assistant-trial-result .assistant-trial-verdict h5').textContent(), 'One small win — not proven yet');
  assert.match(await page.locator('#assistant-trial-result').textContent(), /1 challenge improved · 7 unchanged · 0 worse/);
  assert.match(await page.locator('#assistant-trial-result').textContent(), /two clean wins/);
  assert.deepEqual((await page.locator('#assistant-trial .assistant-trial-actions button:visible').allTextContents()),
    ['Restore the previous setup · recommended'], 'A cautious result has one prominent next action');
  assert.equal(await page.locator('#assistant-trial-keep').isVisible(), false);
  await page.locator('#assistant-trial-alternatives > summary').click();
  assert.equal(await page.locator('#assistant-trial-keep').textContent(), 'Keep “Show the source”');
  await page.locator('#assistant-trial-alternatives > summary').click();
  await shot('4-result-one-gain-restore');
  forcedTrialResult = result;
  await page.evaluate(() => refreshAssistantTrial());
  forcedTrialResult = null;
  await page.unroute('**/api/assistant-trial');
  assert.equal(await page.locator('#assistant-trial-result .assistant-trial-verdict h5').textContent(), 'Better on this retest');

  // ---- Keep, verified; then Restore, verified byte-exact by the controller.
  await page.locator('#assistant-trial-keep').click();
  await page.waitForFunction(async () => (await api('/api/assistant-trial')).status === 'kept', null, {polling: 300});
  assert.match(await page.locator('#assistant-trial-note').textContent(), /Kept and verified/);
  assert.equal(await page.locator('#assistant-trial-result .assistant-trial-verdict h5').textContent(), 'Change kept');
  assert.equal(await page.locator('#assistant-trial-next-round').isVisible(), false, 'The one GO campaign tested every starter idea');
  assert.equal(await page.locator('#assistant-trial-chat').isVisible(), true, 'After the campaign, the next step is trying a real question');
  assert.equal(await page.locator('#assistant-trial-chat').isDisabled(), await page.locator('#chat').isDisabled(),
    'The next-step button follows live chat availability; this fixture has no chat endpoint');
  assert.match(await page.locator('#assistant-trial-result').textContent(), /restore the original any time/);
  assert.deepEqual((await page.locator('#assistant-trial .assistant-trial-actions button:visible').allTextContents()),
    ['Try it with a real question'], 'After Keep, trying the assistant is the single primary action');
  assert.equal(await page.locator('#command-center').evaluate(el => el.classList.contains('assistant-trial-focus')), true,
    'Keep continues the focused flow into the real-question follow-up');
  assert.equal(await page.locator('#assistant-trial-restore').isVisible(), false,
    'Restore stays available as an explicit undo, not a competing primary action');
  await shot('5-kept');
  await page.locator('#assistant-trial-alternatives > summary').click();
  await page.locator('#assistant-trial-restore').click();
  await page.waitForFunction(async () => { const v = await api('/api/assistant-trial'); return v.status === 'none' && v.phase === 'restored'; },
    null, {timeout: 20000, polling: 300});
  await page.waitForFunction(() => /Restored and verified: AGENTS.md is byte-for-byte the original/.test(document.getElementById('assistant-trial-note').textContent));
  assert.equal(await page.locator('#cc-next').isHidden(), false,
    'The main mission card returns after Restore');
  assert.equal(await page.locator('#command-center').evaluate(el => el.classList.contains('assistant-trial-focus')), false,
    'The focused mode ends when the choice is resolved');
  const restoredSections = ['#receipt-extra-details', '#cc-receipt-kicker', '#cc-receipt-title', '#cc-takeaway',
    '#cc-strengths-disclosure', '#cc-evidence-disclosure', '#cc-diagnostics-disclosure',
    '#example-missions', '#cc-progress-journal', '#cc-task-box', '#full-skill-map'];
  await page.waitForFunction(ids => ids.every(id => {
    const el = document.querySelector(id);
    return el && !el.hidden && getComputedStyle(el).display !== 'none';
  }), restoredSections, {timeout: 10000});
  for (const id of restoredSections) {
    assert.equal(await page.locator(id).isHidden(), false,
      `${id} returns after the focused assistant decision is complete`);
  }
  assert.equal(await page.locator('#cc-next-go').getAttribute('data-action'), 'assistant-trial',
    'The improvement loop is ready to run again after Restore');
  assert.match(await page.locator('#assistant-trial-note').textContent(), /Restored and verified/,
    'The restore confirmation stays visible while the next GO is available');
  await shot('6-restored');

  // A first-answer failure leaves the assistant unchanged and offers one safe retry.
  let forcedFailure = true;
  await page.route('**/api/assistant-trial', async route => {
    const response = await route.fetch();
    const payload = await response.json();
    if (forcedFailure) Object.assign(payload, {active: false, phase: 'failed', result_state: 'failed', status: 'none',
      failure_code: 'assistant-error', message: 'Your local AI could not finish its first test answer. No idea was changed.'});
    await route.fulfill({response, body: JSON.stringify(payload)});
  });
  await page.evaluate(() => refreshAssistantTrial());
  assert.equal(await page.locator('#assistant-trial-title').textContent(), 'This run stopped safely');
  assert.match(await page.locator('#assistant-trial-text').textContent(), /No idea was changed/);
  assert.equal(await page.locator('#assistant-trial .assistant-trial-actions').isVisible(), true,
    'A safe, unchanged failure keeps the next action available');
  assert.deepEqual((await page.locator('#assistant-trial .assistant-trial-actions button:visible').allTextContents()),
    ['Try this round again'], 'A failed run has one obvious retry and no misleading Keep/Restore choices');
  assert.equal(await page.locator('#assistant-trial-keep').isVisible(), false);
  assert.equal(await page.locator('#assistant-trial-restore').isVisible(), false);
  await shot('7-failure-retry');
  forcedFailure = false;
  await page.unroute('**/api/assistant-trial');

  // Cancellation must recover without leaving the approved instruction applied.
  await page.evaluate(() => { commandAction = {action: 'assistant-trial'}; });
  await page.locator('#cc-next-go').click();
  await page.locator('#assistant-trial-cancel').waitFor({state: 'visible'});
  await page.locator('#assistant-trial-cancel').click();
  await page.waitForFunction(async () => { const v = await api('/api/assistant-trial'); return !v.active && v.status === 'none' && v.phase === 'cancelled'; },
    null, {timeout: 20000, polling: 300});

  // ---- Diagnostic-only misses recommend reviewing them, not a larger model.
  const proposal = await page.evaluate(() => nextExperiment({suite: 'documents-short', recipe: {preset: 'standard'}, total: 24, correct: 20,
    format_errors: 0, wrong_answers: 4, diagnoses: {wording: 2, requirement: 2}}));
  assert.equal(proposal.kind, 'review');
  assert.match(proposal.why, /^Diagnostic, not a score: every miss kept an accepted answer/);

  const cautious = await page.evaluate(() => assistantTrialDecision({rows: Array(8).fill({}), gains: ['one'], regressions: [], suggestion: 'restore'}, 'on-trial'));
  assert.equal(cautious.title, 'One small win — not proven yet');
  assert.match(cautious.next, /two clean wins/);
  const mixed = await page.evaluate(() => assistantTrialDecision({rows: Array(8).fill({}), gains: ['one'], regressions: ['two'], suggestion: 'restore'}, 'on-trial'));
  assert.equal(mixed.title, 'Mixed results');
  assert.match(mixed.next, /restore the original/);
  const wrongFacts = await page.evaluate(() => nextExperiment({suite: 'documents-short', recipe: {preset: 'standard'}, total: 24, correct: 20,
    format_errors: 0, wrong_answers: 4, diagnoses: {wrong: 3, wording: 1}}));
  assert.equal(wrongFacts.kind, 'model');

  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({width, height: 844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `No overflow at ${width}`);
  }
  const ids = await page.locator('[id]').evaluateAll(nodes => nodes.map(n => n.id));
  assert.equal(new Set(ids).size, ids.length, 'Unique control IDs');
  assert.deepEqual(errors, []);
  console.log('PASS: one GO starts the disclosed U10 trial, Keep/Restore and safe failure retry verified; fixture only.');
} finally { if (browser) await browser.close(); server.stdin.end(); server.kill(); }
