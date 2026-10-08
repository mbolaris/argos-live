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

  console.log('All Mission First J5, J6b, J7, and J8 checks passed successfully!');
} finally {
  if (browser) await browser.close();
  server.kill();
}
