// Regression tests for J5 mission-first home corrections:
// 1. "Start: Read this brief" is the single primary action, visible without scrolling at 390x844.
// 2. Starts exactly one documents workload, disabled while busy.
// 3. Truthful assistant recovery state (delayed in-progress, failed, ready) without unconditional claims.
// 4. Cancellation retains partial challenge answers and marks stream incomplete.
// 5. Hero result displays three qualification states (Qualified, Criteria not met, Not assessed).

import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');

const defaultPython = process.platform === 'win32' ? 'py' : 'python3';
const pythonCmd = process.env.ARGOS_PYTHON || defaultPython;
const server = spawn(pythonCmd, ['-u', 'scripts/serve-journey-fixture.py'], {stdio: ['pipe', 'pipe', 'inherit']});
let browser;
const fail = (message) => { throw new Error(message); };

try {
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 25000);
    createInterface({input: server.stdout}).once('line', line => { clearTimeout(timer); done(line.trim()); });
    server.once('error', reject);
  });

  browser = await chromium.launch({headless: true});

  // Mobile viewport: 390 x 844 (phone screen)
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('503')) errors.push('console: ' + m.text()); });

  await page.goto(url);

  // Wait for command center to load and resolve next action
  await page.waitForFunction(() => document.getElementById('cc-next-title')?.textContent === 'Read this brief', null, {timeout: 30000});

  // 1. Single primary action: #cc-start-documents-quick does not exist
  const quickCount = await page.locator('#cc-start-documents-quick').count();
  if (quickCount !== 0) fail(`Old duplicate documents button still exists in DOM (count: ${quickCount})`);

  // Verify #cc-next-go is visible and labeled "Start: Read this brief"
  const startBtn = page.locator('#cc-next-go');
  if (!(await startBtn.isVisible())) fail('Primary Start button is not visible');
  const btnText = (await startBtn.textContent()).trim();
  if (btnText !== 'Start: Read this brief') fail(`Unexpected primary button text: "${btnText}"`);

  // Assert that the Start button is visible without scrolling at 390x844
  const box = await startBtn.boundingBox();
  if (!box) fail('Could not measure Start button bounding box');
  const bottom = box.y + box.height;
  if (box.y < 0 || bottom > 844) {
    fail(`Start button is not above the fold at 390x844 (y=${box.y.toFixed(1)}, bottom=${bottom.toFixed(1)}, viewport height=844)`);
  }
  console.log(`[PASS] Start button visible above the fold at 390x844 (y=${box.y.toFixed(1)}, bottom=${bottom.toFixed(1)})`);

  // Hero result initial state: "Not yet tested"
  const initialHeroResult = (await page.locator('#cc-hero-result').textContent()).trim();
  if (initialHeroResult !== 'Not yet tested') fail(`Initial hero result expected 'Not yet tested', got: "${initialHeroResult}"`);

  // 2. Starts exactly one documents workload, disabled while busy
  const docStarted = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
  await startBtn.click();
  const startResp = await docStarted;
  if (!startResp.ok()) fail('Document start request failed');

  // Verify primary button is disabled while busy
  await page.waitForFunction(() => document.getElementById('cc-next-go').disabled === true, null, {timeout: 5000});
  const isDisabled = await page.evaluate(() => document.getElementById('cc-next-go').disabled);
  if (!isDisabled) fail('Start button was not disabled while workload is running');

  // Verify second concurrent start attempt fails (exactly one documents workload)
  const concurrentAttempt = await page.evaluate(async () => {
    try {
      const res = await fetch('/api/lab/start-documents', {method: 'POST', headers: {'X-Argos-Token': token || ''}});
      return {ok: res.ok, status: res.status};
    } catch (e) {
      return {ok: false, error: e.message};
    }
  });
  if (concurrentAttempt.ok) fail('Concurrent workload was unexpectedly permitted');
  console.log('[PASS] Single documents workload enforced; Start button disabled while busy');

  // 3. Stream and arena item scoring
  await page.waitForFunction(() => {
    const list = document.querySelectorAll('#arena-receipts-list .arena-receipt-row');
    return list.length >= 1;
  }, null, {timeout: 60000});
  console.log('[PASS] Evaluated at least one challenge in documents trial');

  // 4. Test cancellation with retained partial answers
  const cancelResp = page.waitForResponse(r => r.url().endsWith('/api/lab/cancel') && r.request().method() === 'POST');
  await page.locator('#lab-cancel').click();
  const cancelled = await cancelResp;
  if (!cancelled.ok()) fail('Cancel request failed');

  // Wait for terminal stopped state
  try {
    await page.waitForFunction(() => {
      const badge = document.getElementById('arena-phase-badge');
      return badge && badge.textContent.includes('STOPPED');
    }, null, {timeout: 30000});
  } catch (e) {
    const b = await page.locator('#arena-phase-badge').textContent();
    const h = await page.locator('#arena-summary-headline').textContent();
    const s = await page.locator('#lab-status').textContent();
    console.error(`DEBUG: Badge="${b}", Headline="${h}", Lab status="${s}"`);
    throw e;
  }

  const headline = (await page.locator('#arena-summary-headline').textContent()).trim();
  if (headline !== 'Stopped · incomplete') fail(`Expected 'Stopped · incomplete', got '${headline}'`);

  const detail = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (detail.includes('Assistant resumption ready')) {
    fail(`Unconditional 'Assistant resumption ready' found in summary detail: "${detail}"`);
  }
  if (!detail.includes('(incomplete)')) fail(`Summary detail missing '(incomplete)': "${detail}"`);
  if (!detail.includes('challenges evaluated')) fail(`Summary detail missing challenge count: "${detail}"`);
  console.log(`[PASS] Truthful cancellation summary detail: "${detail}"`);

  // Current stream ends with [Stopped · incomplete]
  const streamText = (await page.locator('#arena-current-stream').textContent()).trim();
  if (!streamText.includes('[Stopped · incomplete]')) {
    fail(`Stream text does not indicate stoppage: "${streamText}"`);
  }

  // Partial receipts table retained
  const receiptCount = await page.locator('#arena-receipts-list .arena-receipt-row').count();
  if (receiptCount < 1) fail('Partial receipts were lost on cancellation');
  console.log(`[PASS] Partial results preserved on cancellation (${receiptCount} receipts retained)`);

  // 5. Test rendered assistant recovery transitions: ready -> new trial -> recovering -> ready/failed, including reload
  // Initial cancellation state shows in-progress recovery
  if (!detail.endsWith('Assistant recovery in progress.')) {
    fail(`Cancellation detail did not end with 'Assistant recovery in progress.': "${detail}"`);
  }
  console.log(`[PASS] Initial cancellation banner rendered in-progress recovery: "${detail}"`);

  // Step 5a: Transition recovering -> ready via real refreshStartup()
  await page.route('**/api/startup', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schema: 'argos-startup/1',
        managed: true,
        phase: 'ready',
        message: 'Ready for conversation',
        active: false,
        model_reply_verified: true,
      }),
    });
  });
  await page.evaluate(async () => { await refreshStartup(); });
  const readyDetail = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (!readyDetail.endsWith('Assistant ready.')) {
    fail(`Rendered detail did not update to 'Assistant ready.': "${readyDetail}"`);
  }
  console.log(`[PASS] Rendered recovering -> ready transition: "${readyDetail}"`);

  // Step 5b: Start a NEW trial (ready -> new trial)
  await page.unroute('**/api/startup');
  const newTrialStarted = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
  await page.evaluate(() => focusSection('lab-controls'));
  await page.locator('#lab-start-documents').click();
  await newTrialStarted;

  // Wait for new trial to evaluate at least one item
  await page.waitForFunction(() => {
    const rows = document.querySelectorAll('#arena-receipts-list .arena-receipt-row');
    return rows.length >= 1;
  }, null, {timeout: 30000});

  // Step 5c: Cancel the new trial with a delayed startup response (new trial -> recovering)
  // An older / delayed /api/startup response must NOT override newer recovery evidence from the current Lab run.
  let deliverDelayedStartup;
  const startupGate = new Promise(r => { deliverDelayedStartup = r; });
  await page.route('**/api/startup', async route => {
    await startupGate;
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schema: 'argos-startup/1',
        managed: true,
        phase: 'ready', // Older startup response claiming ready
        message: 'Ready for conversation',
        active: false,
        model_reply_verified: true,
      }),
    });
  });
  const cancelResp2 = page.waitForResponse(r => r.url().endsWith('/api/lab/cancel') && r.request().method() === 'POST');
  await page.locator('#lab-cancel').click();
  await cancelResp2;

  await page.waitForFunction(() => {
    const badge = document.getElementById('arena-phase-badge');
    return badge && badge.textContent.includes('STOPPED');
  }, null, {timeout: 30000});

  // Check the cancellation banner BEFORE that startup response arrives!
  const earlyDetail = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (earlyDetail.includes('Assistant ready.')) {
    fail(`Older startup response leaked into cancellation banner before startup response arrived: "${earlyDetail}"`);
  }
  if (!earlyDetail.endsWith('Assistant recovery in progress.')) {
    fail(`Before delayed startup response arrived, cancellation banner did not show in-progress recovery: "${earlyDetail}"`);
  }
  console.log(`[PASS] Cancellation banner correctly shows in-progress recovery before delayed startup response arrives: "${earlyDetail}"`);

  // Deliver the delayed older startup response
  deliverDelayedStartup();
  await page.waitForTimeout(100);

  // Assert that the older /api/startup response did NOT override newer recovery evidence from the current Lab run
  const afterOlderDetail = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (!afterOlderDetail.endsWith('Assistant recovery in progress.')) {
    fail(`Older /api/startup response overrode newer recovery evidence from current Lab run: "${afterOlderDetail}"`);
  }
  console.log('[PASS] Older /api/startup response did not override newer recovery evidence from current Lab run');

  // Step 5d: Transition recovering -> failed on the new trial
  await page.route('**/api/startup', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schema: 'argos-startup/1',
        managed: true,
        phase: 'failed',
        message: 'Startup failed',
        active: false,
      }),
    });
  });
  await page.evaluate(async () => { await refreshStartup(); });
  const newFailedDetail = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (!newFailedDetail.endsWith('Assistant recovery failed.')) {
    fail(`Rendered detail did not update to 'Assistant recovery failed.': "${newFailedDetail}"`);
  }
  console.log(`[PASS] New trial recovery transitioned to failed: "${newFailedDetail}"`);

  // Step 5e: Test reload retains current run recovery and updates on reload
  await page.reload();
  await page.waitForFunction(() => {
    const detailEl = document.getElementById('arena-summary-detail');
    return detailEl && detailEl.textContent.includes('challenges evaluated');
  }, null, {timeout: 30000});

  await page.evaluate(async () => { await refreshStartup(); });
  const reloadedFailed = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (!reloadedFailed.endsWith('Assistant recovery failed.')) {
    fail(`After reload, expected 'Assistant recovery failed.', got: "${reloadedFailed}"`);
  }
  console.log(`[PASS] Recovery status preserved across page reload: "${reloadedFailed}"`);

  // Transition to ready after reload
  await page.route('**/api/startup', route => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        schema: 'argos-startup/1',
        managed: true,
        phase: 'ready',
        message: 'Ready for conversation',
        active: false,
        model_reply_verified: true,
      }),
    });
  });
  await page.evaluate(async () => { await refreshStartup(); });
  const reloadedReady = (await page.locator('#arena-summary-detail').textContent()).trim();
  if (!reloadedReady.endsWith('Assistant ready.')) {
    fail(`After reload, transition to ready failed: "${reloadedReady}"`);
  }
  console.log(`[PASS] Transition to ready succeeded after page reload: "${reloadedReady}"`);
  await page.unroute('**/api/startup');

  // 6. Test rendered hero result qualification tri-state in #cc-hero-result
  const baseCommandData = await page.evaluate(async () => {
    const res = await fetch('/api/command-center', {headers: {'X-Argos-Token': token || ''}});
    return res.json();
  });

  // a) Baseline report (no qualification): "Not assessed", NOT "Missed"
  await page.route('**/api/command-center', route => {
    const data = JSON.parse(JSON.stringify(baseCommandData));
    data.report = {
      plan: 'baseline',
      ability: {correct: 8, total: 8, qualified: null},
    };
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  await page.evaluate(async () => { await refreshCommand(); });
  const baselineHero = (await page.locator('#cc-hero-result').textContent()).trim();
  if (baselineHero !== '8/8 (Not assessed)') fail(`Baseline expected '8/8 (Not assessed)', got '${baselineHero}'`);
  if (baselineHero.includes('Missed')) fail(`Baseline qualification displayed Missed instead of Not assessed: "${baselineHero}"`);
  console.log(`[PASS] Rendered baseline qualification in #cc-hero-result: "${baselineHero}"`);

  // b) Document trial met criteria: "Qualified"
  await page.route('**/api/command-center', route => {
    const data = JSON.parse(JSON.stringify(baseCommandData));
    data.report = {
      plan: 'documents',
      ability: {correct: 8, total: 8, qualified: true},
    };
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  await page.evaluate(async () => { await refreshCommand(); });
  const metHero = (await page.locator('#cc-hero-result').textContent()).trim();
  if (metHero !== '8/8 (Qualified)') fail(`Met qualification expected '8/8 (Qualified)', got '${metHero}'`);
  console.log(`[PASS] Rendered qualified document trial in #cc-hero-result: "${metHero}"`);

  // c) Document trial failed criteria: "Criteria not met"
  await page.route('**/api/command-center', route => {
    const data = JSON.parse(JSON.stringify(baseCommandData));
    data.report = {
      plan: 'documents',
      ability: {correct: 5, total: 8, qualified: false},
    };
    route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  await page.evaluate(async () => { await refreshCommand(); });
  const notMetHero = (await page.locator('#cc-hero-result').textContent()).trim();
  if (notMetHero !== '5/8 (Criteria not met)') fail(`Failed qualification expected '5/8 (Criteria not met)', got '${notMetHero}'`);
  console.log(`[PASS] Rendered criteria not met in #cc-hero-result: "${notMetHero}"`);
  await page.unroute('**/api/command-center');

  // J6b: Recipe experiment modal, selection, and restoration
  await page.locator('#receipt-change').click();
  const modalOpen = await page.locator('#recipe-modal').evaluate(el => el.open);
  if (!modalOpen) fail('#receipt-change did not open #recipe-modal');
  const quoteText = await page.locator('.recipe-instruction-quote').textContent();
  if (!quoteText.includes('Follow the requested output format')) fail('Recipe modal missing concise instruction text');
  const protectionText = await page.locator('.recipe-protection-notice').textContent();
  if (!protectionText.includes('Lab test recipe only')) fail('Recipe modal missing assistant protection notice');
  console.log('[PASS] Recipe experiment modal opened with concise instruction preview and assistant protection notice');

  await page.locator('#recipe-select-only').click();
  await page.waitForTimeout(200);
  const activeRecipeText = (await page.locator('#lab-active-recipe').textContent()).trim();
  if (!activeRecipeText.includes('concise') && !activeRecipeText.includes('Strict format')) {
    fail(`Active Lab recipe was not updated after selection: "${activeRecipeText}"`);
  }
  const restoreBtnHidden = await page.locator('#lab-recipe-restore').evaluate(el => el.hidden);
  if (restoreBtnHidden) fail('Restore button should be visible when non-standard recipe is active');
  console.log(`[PASS] Concise recipe selected as active Lab recipe: "${activeRecipeText}"`);

  await page.evaluate(() => focusSection('lab-controls'));
  await page.locator('#lab-recipe-restore').click();
  await page.waitForTimeout(200);
  const restoredRecipeText = (await page.locator('#lab-active-recipe').textContent()).trim();
  if (!restoredRecipeText.includes('Standard calibration')) {
    fail(`Active Lab recipe was not restored to standard: "${restoredRecipeText}"`);
  }
  const restoreBtnHiddenAfter = await page.locator('#lab-recipe-restore').evaluate(el => el.hidden);
  if (!restoreBtnHiddenAfter) fail('Restore button should be hidden after restoring standard recipe');
  // J7: Controlled experiment button check
  const expBtn = page.locator('#compare-experiment');
  const expCount = await expBtn.count();
  if (expCount !== 1) fail('Expected #compare-experiment button in DOM');
  const expDisabled = await expBtn.evaluate(el => el.disabled);
  if (!expDisabled) fail('#compare-experiment should be disabled initially');
  console.log('[PASS] Controlled experiment button #compare-experiment exists and is disabled initially');

  // J8: Integrated watch / debrief / skill-map and receipt use checks
  const opinionTag = await page.locator('.opinion-tag').textContent();
  if (!opinionTag.includes('Model opinion') || !opinionTag.includes('not scored evidence')) {
    fail(`Expected opinion disclaimer tag, got: "${opinionTag}"`);
  }
  const legendText = await page.locator('.skill-map-legend').textContent();
  if (!legendText.includes('Qualified') || !legendText.includes('Tested') || !legendText.includes('Needs work')) {
    fail(`Expected 3-state legend marks in skill map, got: "${legendText}"`);
  }
  const arenaNextBtn = page.locator('#arena-next-action');
  if (await arenaNextBtn.count() !== 1) fail('Expected #arena-next-action button in DOM');
  const receiptUseBtn = page.locator('#receipt-use');
  if (await receiptUseBtn.count() !== 1) fail('Expected #receipt-use button in DOM');
  console.log('[PASS] J8 debrief opinion disclaimer, 3-state legend, and next-action controls verified');

  // J3: Curated models storefront, inline storage, and model rollback transaction checks
  const curatedDeck = page.locator('#model-curated');
  if (await curatedDeck.count() !== 1) fail('Expected #model-curated storefront deck in DOM');
  await page.evaluate(() => focusSection('models-title'));
  const inlineStorageSec = page.locator('#inline-storage-section');
  if (await inlineStorageSec.count() !== 1) fail('Expected #inline-storage-section in DOM');
  const rollbackBar = page.locator('#receipt-model-rollback-bar');
  if (await rollbackBar.count() !== 1) fail('Expected #receipt-model-rollback-bar in DOM');
  const restoreModelBtn = page.locator('#receipt-restore-model');
  if (await restoreModelBtn.count() !== 1) fail('Expected #receipt-restore-model button in DOM');
  const keepModelBtn = page.locator('#receipt-keep-model');
  if (await keepModelBtn.count() !== 1) fail('Expected #receipt-keep-model button in DOM');
  console.log('[PASS] J3 curated storefront, inline storage, and model rollback controls verified');

  // Playable Loop Redesign regressions:
  // 1. Single Curriculum Map with 6 K-12 foundation rungs
  const curriculumMap = page.locator('#curriculum-map');
  if (await curriculumMap.count() !== 1) fail('Expected #curriculum-map in DOM');
  const rungsCount = await page.locator('#curriculum-map .curriculum-rung').count();
  if (rungsCount !== 6) fail(`Expected 6 curriculum rungs, found ${rungsCount}`);
  const activeRungText = await page.locator('#curriculum-map .curriculum-rung.active').textContent();
  if (!activeRungText.includes('Short Document Comprehension')) {
    fail(`Active rung expected 'Short Document Comprehension', got: "${activeRungText}"`);
  }
  console.log('[PASS] K-12 foundation curriculum progression map verified (6 rungs, Short Document Comprehension active)');

  // 2. Hardware diagnostic schematic moved to secondary details container
  const schematicBay = page.locator('.secondary-details-bay #cc-schematic');
  if (await schematicBay.count() !== 1) fail('Expected #cc-schematic inside .secondary-details-bay');
  console.log('[PASS] Hardware diagnostic schematic preserved in secondary details bay');

  // 3. Storage modal fixed layout with sticky header/footer and destination grouping
  const stickyHeader = page.locator('#download-review .modal-sticky-header');
  const stickyFooter = page.locator('#download-review .modal-sticky-footer');
  if (await stickyHeader.count() !== 1 || await stickyFooter.count() !== 1) {
    fail('Expected sticky header and footer in #download-review');
  }
  console.log('[PASS] Storage modal fixed layout with sticky header and footer verified');

  // 4. Mobile responsiveness check at 320px
  await page.setViewportSize({width: 320, height: 844});
  const overflow320 = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  if (overflow320) fail('Layout overflows at 320px viewport width');
  console.log('[PASS] Mobile responsiveness verified at 320px without layout overflow');

  // 5. Home page hierarchy: verify redundant intros removed
  const subTitleCount = await page.locator('.cc-subtitle').count();
  const pauseNoticeCount = await page.locator('.cc-pause-notice').count();
  if (subTitleCount !== 0) fail('Expected .cc-subtitle to be removed to eliminate duplicate home intro');
  if (pauseNoticeCount !== 0) fail('Expected .cc-pause-notice to be removed to eliminate duplicate pause notice');
  console.log('[PASS] Repeated home-page introductions verified removed');

  // 6. Arena hierarchy & Watch HUD compact layout: question/stream first, source collapsed, no vertical gap blowout
  const questionEl = page.locator('#arena-current-question');
  if (await questionEl.count() !== 1) fail('Expected #arena-current-question in DOM');
  const arenaHierarchyValid = await page.evaluate(() => {
    const q = document.getElementById('arena-current-question');
    const s = document.getElementById('arena-current-stream');
    const src = document.getElementById('arena-source-details');
    const prompt = document.getElementById('arena-current-prompt');
    const hud = document.querySelector('.arena-hud');
    const progress = document.querySelector('.arena-hud-progress');
    const deck = document.getElementById('arena');
    if (!q || !s || !src || !prompt || !hud || !progress || !deck) return false;
    const qBeforeS = (q.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    const sBeforeSrc = (s.compareDocumentPosition(src) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    const srcContainsPrompt = src.contains(prompt);
    const srcCollapsed = src.open === false;

    // Computed layout checks: HUD and progress must be compact (no 200px/395px blowout)
    const hudHeight = hud.getBoundingClientRect().height;
    const progHeight = progress.getBoundingClientRect().height;
    const deckPaddingTop = parseFloat(window.getComputedStyle(deck).paddingTop);
    const compactHud = hudHeight <= 180 && progHeight <= 60 && deckPaddingTop <= 16;

    return qBeforeS && sBeforeSrc && srcContainsPrompt && srcCollapsed && compactHud;
  });
  if (!arenaHierarchyValid) fail('Arena hierarchy or computed HUD layout invalid: check question/stream order and computed gaps');
  const sourceSummaryText = await page.locator('#arena-source-details summary').textContent();
  if (!sourceSummaryText.includes('Read source')) fail(`Expected 'Read source' summary, got: "${sourceSummaryText}"`);
  console.log('[PASS] Arena hierarchy & compact Watch HUD verified: question/stream first, source collapsed, compact HUD height <= 180px');

  // 7. Debrief hierarchy: "Use this build" as sole primary action when qualified, secondary options & metrics collapsed under Details
  await page.route('**/api/command-center', route => {
    const data = {
      available: true,
      name: 'Argos',
      model: 'fixture:latest',
      report: {
        speed: { tokens_per_second: 20.0, prompt_tokens_per_second: 100.0, first_token_seconds: 0.2 },
        ability: { correct: 8, total: 8, qualified: true, suite: 'documents-short' },
      },
      next_action: { title: 'Use this build', action: 'task' },
      systems: [],
      journal: []
    };
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.evaluate(async () => { await refreshCommand(); });

  const debriefHierarchyValid = await page.evaluate(() => {
    const takeaway = document.getElementById('cc-takeaway');
    const actions = document.getElementById('receipt-actions');
    const replay = document.getElementById('receipt-replay');
    const useBtn = document.getElementById('receipt-use');
    const changeBtn = document.getElementById('receipt-change');
    const secOptions = document.getElementById('receipt-secondary-options');
    const metricsDetails = document.getElementById('receipt-metrics-details');
    const scoreboard = document.getElementById('cc-scoreboard');
    const criteriaBox = document.getElementById('receipt-criteria-box');

    if (!takeaway || !actions || !replay || !useBtn || !secOptions || !metricsDetails) {
      return { valid: false, reason: 'Missing essential debrief elements' };
    }

    const takeawayBeforeReplay = (takeaway.compareDocumentPosition(replay) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    const actionsBeforeReplay = (actions.compareDocumentPosition(replay) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    if (!takeawayBeforeReplay || !actionsBeforeReplay) {
      return { valid: false, reason: 'Takeaway or actions do not precede replay details' };
    }

    // Verify "Use this build" is the sole visible primary action in #receipt-actions
    const isVisible = el => !el.hidden && (el.checkVisibility ? el.checkVisibility() : true);
    const visiblePrimaryButtons = Array.from(actions.querySelectorAll('.mission-primary')).filter(isVisible);
    if (visiblePrimaryButtons.length !== 1 || !visiblePrimaryButtons[0].textContent.includes('Use this build')) {
      return { valid: false, reason: `Expected 1 primary button ('Use this build'), found ${visiblePrimaryButtons.length}` };
    }

    // Verify secondary options collapsed under Details
    if (secOptions.open !== false) {
      return { valid: false, reason: 'Expected #receipt-secondary-options to be collapsed when qualified' };
    }
    if (!secOptions.contains(changeBtn)) {
      return { valid: false, reason: 'Expected #receipt-change to be inside #receipt-secondary-options' };
    }

    // Verify metrics and criteria collapsed under Details
    if (metricsDetails.open !== false) {
      return { valid: false, reason: 'Expected #receipt-metrics-details to be collapsed when qualified' };
    }
    if (!metricsDetails.contains(scoreboard) || !metricsDetails.contains(criteriaBox)) {
      return { valid: false, reason: 'Expected scoreboard and criteria checklist inside #receipt-metrics-details' };
    }

    return { valid: true };
  });

  if (!debriefHierarchyValid.valid) {
    fail(`Debrief hierarchy regression failed: ${debriefHierarchyValid.reason}`);
  }
  await page.unroute('**/api/command-center');
  console.log('[PASS] Debrief hierarchy verified: "Use this build" sole primary action, secondary options and metrics collapsed under Details');

  // 8. Storage hierarchy, compact strip & computed layout: compact strip (<150px), compact card (<300px), compact padding, collapsed path/policies, no read-only claims
  await page.evaluate(async () => {
    window.resetStorageForReview();
    const tag = 'qwen2.5:1.5b-instruct-q4_K_M';
    await window.reviewDownload({ tag }, tag);
  });
  await page.waitForFunction(() => document.getElementById('download-review')?.open);

  const storageHierarchyValid = await page.evaluate(() => {
    const modal = document.getElementById('download-review');
    const recCard = modal.querySelector('.destination-card.recommended');
    if (!recCard) return { valid: false, reason: 'No recommended destination card found' };

    // Compact strip with drive name, space, and button together
    const strip = recCard.querySelector('.dest-compact-strip');
    if (!strip) return { valid: false, reason: 'Missing .dest-compact-strip in recommended card' };

    const nameTitle = strip.querySelector('.dest-name-title');
    const spaceRow = strip.querySelector('.dest-space-row');
    const btn = strip.querySelector('.dest-select-btn');
    if (!nameTitle || !spaceRow || !btn) return { valid: false, reason: 'Compact strip missing name, space, or button' };

    // Drive name should be concise (not a raw path)
    if (nameTitle.textContent.includes('/') || nameTitle.textContent.includes('\\')) {
      return { valid: false, reason: `Drive name contains raw path characters: ${nameTitle.textContent}` };
    }

    // Recommended destination must be selectable
    if (btn.disabled) return { valid: false, reason: 'Recommended destination button is disabled' };

    // Path must be collapsed
    const pathDetails = recCard.querySelector('.dest-details-collapse');
    if (!pathDetails || pathDetails.open) return { valid: false, reason: 'Drive path details not collapsed' };

    // Policy guardrails must be collapsed
    const policyDetails = modal.querySelector('.storage-policy-collapse');
    if (!policyDetails || policyDetails.open) return { valid: false, reason: 'Policy guardrails not collapsed' };

    // No unsupported read-only claims
    if (modal.textContent.includes('mounted read-only')) {
      return { valid: false, reason: 'Unsupported read-only claim found in modal text' };
    }

    // Computed layout checks: strip < 150px, card < 300px, modal header/body padding <= 16px
    const stripHeight = strip.getBoundingClientRect().height;
    const cardHeight = recCard.getBoundingClientRect().height;
    const headerPadTop = parseFloat(window.getComputedStyle(modal.querySelector('.modal-sticky-header')).paddingTop);
    const bodyPadTop = parseFloat(window.getComputedStyle(modal.querySelector('.modal-scroll-body')).paddingTop);
    if (stripHeight > 150) return { valid: false, reason: `Strip height excessive: ${stripHeight}px > 150px` };
    if (cardHeight > 300) return { valid: false, reason: `Card height excessive: ${cardHeight}px > 300px` };
    if (headerPadTop > 16 || bodyPadTop > 16) return { valid: false, reason: `Modal padding excessive: header=${headerPadTop}px, body=${bodyPadTop}px` };

    return { valid: true };
  });

  if (!storageHierarchyValid.valid) {
    fail(`Storage hierarchy regression failed: ${storageHierarchyValid.reason}`);
  }
  console.log('[PASS] Storage hierarchy & computed layout verified: compact strip <= 150px, card <= 300px, collapsed path/policies, no read-only claims');

  console.log('All Mission First, Playable Loop, and Storage Acquisition checks passed successfully!');
} finally {
  if (browser) await browser.close();
  server.kill();
}
