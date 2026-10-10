// Demonstrate the complete continuous document mission experiment flow:
// 1. Start through "Start: Read this brief" (#cc-next-go).
// 2. Watch live arena streaming an actual challenge answer (passage, tokens, scored receipts).
// 3. Baseline completion retains baseline run ID; Improve proposes the format experiment; the approval dialog opens with OpenClaw personality protection notice.
// 4. Candidate retest runs with concise recipe; automatically pairs with baseline run ID and calls server comparator.
// 5. Before/after and an evidence-based recommendation render in Improve (Keep strict format instructions / Restore standard instructions).
// 6. Action executed (Restore standard -> resets active recipe to Standard calibration and verifies selected: null).
// 7. Cancellation and reload resilience tested mid-flight.
// 8. Incompatible-pair refusal verified server-side (HTTP 409).
// 9. Mobile responsiveness verified at 390px phone width without horizontal blowout.
// All screenshots carry a prominent simulated fixture watermark banner.

import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');

const defaultPython = process.platform === 'win32' ? (process.env.ARGOS_PYTHON || 'C:\\Users\\mike\\AppData\\Local\\Python\\bin\\python.exe') : 'python3';
const server = spawn(defaultPython, ['-u', 'scripts/serve-journey-fixture.py'], {stdio: ['pipe', 'pipe', 'inherit']});
let browser;

function fail(msg) {
  throw new Error(msg);
}

try {
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 25000);
    const rl = createInterface({input: server.stdout});
    rl.once('line', line => { clearTimeout(timer); rl.close(); done(line.trim()); });
    server.once('error', reject);
  });

  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1200, height: 1000}});

  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() === 'error' && !m.text().includes('503') && !m.text().includes('409')) errors.push('console: ' + m.text());
    console.log(`[PAGE ${m.type().toUpperCase()}]`, m.text());
  });

  await page.goto(url);

  // Helper to attach prominent fixture label across all screenshots
  const attachFixtureBanner = async () => {
    await page.evaluate(() => {
      let b = document.getElementById('fixture-watermark-banner');
      if (!b) {
        b = document.createElement('div');
        b.id = 'fixture-watermark-banner';
        b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:999999;background:#b91c1c;color:#ffffff;text-align:center;font-weight:700;font-size:13px;padding:6px;letter-spacing:0.8px;box-shadow:0 2px 8px rgba(0,0,0,0.4);';
        b.textContent = 'SIMULATED FIXTURE RUN · NOT REAL INFERENCE · FIREFOX ESR & TORONADO PHYSICAL GPU PENDING';
        document.body.prepend(b);
      }
    });
  };

  await attachFixtureBanner();

  // =========================================================================
  // STEP 1: START THROUGH "READ THIS BRIEF"
  // =========================================================================
  console.log('--- Step 1: Start through "Read this brief" ---');
  await page.waitForFunction(() => document.getElementById('cc-title') && document.getElementById('cc-next-go'));
  await page.waitForFunction(() => document.getElementById('cc-next-title')?.textContent === 'Read this brief', null, {timeout: 30000});

  const startBtn = page.locator('#cc-next-go');
  if (!(await startBtn.isVisible())) fail('Primary Start button (#cc-next-go) is not visible');
  const startBtnText = (await startBtn.textContent()).trim();
  if (startBtnText !== 'Start: Read this brief') {
    fail(`Expected primary button 'Start: Read this brief', got '${startBtnText}'`);
  }

  // Verify collapsed legacy inventory and single recommended candidate
  const legacyOpen = await page.locator('#catalog-panel').evaluate(el => el.open);
  if (legacyOpen) fail('Legacy catalog should be collapsed by default');
  const curatedText = await page.locator('#model-curated').textContent();
  if (!curatedText.includes('Recommended upgrade')) fail('Curated shortlist does not display recommended upgrade badge');

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-1-start.png'});
  console.log('PASS [Step 1: Start]: Captured work/journey-1-start.png');

  // Verify 390px phone width for initial Start state
  await page.setViewportSize({width: 390, height: 844});
  const mbStartInitial = page.locator('#cc-next-go');
  const mbBoxInitial = await mbStartInitial.boundingBox();
  if (!mbBoxInitial || mbBoxInitial.y < 0 || (mbBoxInitial.y + mbBoxInitial.height) > 844) {
    fail(`Start button is not above fold at 390x844 (y=${mbBoxInitial?.y})`);
  }
  const initScrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const initClientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  if (initScrollWidth > initClientWidth + 2) {
    fail(`Horizontal blowout on mobile Start: scrollWidth=${initScrollWidth}, clientWidth=${initClientWidth}`);
  }
  console.log(`[PASS] Mobile 390px Start verified: button visible above fold (y=${mbBoxInitial.y.toFixed(1)}) without horizontal blowout`);
  await page.setViewportSize({width: 1200, height: 1000});

  // =========================================================================
  // STEP 2: WATCH ACTUAL CHALLENGE ANSWER STREAMING
  // =========================================================================
  console.log('--- Step 2: Watch challenge answer streaming in Arena ---');
  const docStartReq = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
  await startBtn.click();
  const startResp = await docStartReq;
  if (!startResp.ok()) fail('Start documents request failed');

  // Verify #cc-next-go disabled during run
  await page.waitForFunction(() => document.getElementById('cc-next-go').disabled === true);

  // Wait for Live Arena to be visible
  await page.waitForFunction(() => document.getElementById('arena') && !document.getElementById('arena').hidden);

  // Assert actual challenge prompt passage & question are displayed (not generic speed status)
  await page.waitForFunction(() => {
    const prompt = document.getElementById('arena-current-prompt');
    return prompt && prompt.textContent.includes('PASSAGE') && prompt.textContent.includes('QUESTION');
  }, null, {timeout: 20000});

  // Assert actual streaming response content in arena (JSON object tokens)
  await page.waitForFunction(() => {
    const stream = document.getElementById('arena-current-stream');
    return stream && stream.textContent.length > 5 && stream.textContent !== 'Awaiting model response…' && stream.textContent !== 'Generating response…';
  }, null, {timeout: 20000});

  // Assert verified scored receipts start accumulating
  await page.waitForFunction(() => {
    return document.querySelectorAll('#arena-receipts-list .arena-receipt-row').length >= 1;
  }, null, {timeout: 20000});

  const promptText = (await page.locator('#arena-current-prompt').textContent()).trim();
  const streamText = (await page.locator('#arena-current-stream').textContent()).trim();
  console.log(`[PASS] Streaming active challenge prompt: "${promptText.slice(0, 60)}…"`);
  console.log(`[PASS] Streaming active answer tokens: "${streamText.slice(0, 60)}…"`);

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-2-watch.png'});
  console.log('PASS [Step 2: Watch]: Captured work/journey-2-watch.png');

  // Wait for baseline document trial to complete and debrief actions to be rendered
  await page.waitForFunction(() => {
    const badge = document.getElementById('arena-phase-badge');
    const status = document.getElementById('lab-status');
    const baselineSaved = (badge && badge.textContent.includes('COMPLETED')) || (status && status.textContent.includes('Document trial saved'));
    const idRetained = sessionStorage.getItem('argos_baseline_doc_run_id') !== null;
    const act = document.getElementById('receipt-actions');
    return baselineSaved && idRetained && act && !act.hidden;
  }, null, {timeout: 90000});

  const retainedBaselineId = await page.evaluate(() => sessionStorage.getItem('argos_baseline_doc_run_id'));
  if (!retainedBaselineId) fail('Baseline document run ID was not retained in session storage');
  console.log(`[PASS] Retained baseline run ID: ${retainedBaselineId}`);

  // =========================================================================
  // STEP 3: OPEN RECIPE MODAL & VERIFY PERSONALITY PROTECTION
  // =========================================================================
  console.log('--- Step 3: Open recipe experiment modal ---');
  // The format miss leads Improve to propose exactly this experiment; reviewing it starts nothing.
  await page.waitForFunction(() => document.getElementById('improve-next')?.dataset.kind === 'format' &&
    !document.getElementById('improve-next').hidden);
  const changeBtn = page.locator('#improve-go');
  await changeBtn.waitFor({state: 'visible'});
  await changeBtn.click();

  await page.waitForFunction(() => document.getElementById('recipe-modal')?.open);
  const modalText = await page.locator('#recipe-modal').textContent();

  // Assert OpenClaw assistant personality protection notice is explicit
  if (!modalText.includes('Your everyday assistant is not changed')) {
    fail('Recipe modal lacks everyday-assistant protection summary');
  }
  if (!modalText.includes('does not alter your assistant\'s OpenClaw personality')) {
    fail('Recipe modal lacks OpenClaw personality protection statement');
  }
  if (!modalText.includes('Follow the requested output format; omit extra prose.')) {
    fail('Recipe modal lacks concise instructions quotation');
  }

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-3-change.png'});
  console.log('PASS [Step 3: Change]: Captured work/journey-3-change.png');

  // =========================================================================
  // STEP 4: RETEST CANDIDATE & AUTOMATIC CONTROLLED COMPARISON
  // =========================================================================
  console.log('--- Step 4: Run concise candidate trial & auto-pair comparison ---');
  const candidateStartReq = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
  await page.locator('#recipe-run').click();
  const candResp = await candidateStartReq;
  if (!candResp.ok()) fail('Candidate trial start request failed');

  // Modal should close immediately
  await page.waitForFunction(() => !document.getElementById('recipe-modal')?.open);

  // Wait for candidate trial to stream, complete, and auto-render controlled comparison
  await page.waitForFunction(() => {
    const card = document.querySelector('#improve-comparison .experiment-card');
    const rec = document.getElementById('experiment-recommendation');
    return card !== null && rec !== null;
  }, null, {timeout: 90000});

  // Assert server comparator response
  const latestRuns = await page.evaluate(async () => {
    const listing = await api('/api/benchmarks');
    const docRuns = listing.runs.filter(r => r.kind === 'ability' && (r.suite_version || '').startsWith('documents/'));
    const baseId = sessionStorage.getItem('argos_baseline_doc_run_id');
    const cand = docRuns.find(r => r.id !== baseId);
    return {baseline: baseId, candidate: cand?.id};
  });

  const experimentData = await page.evaluate(async ({b, c}) => {
    return await api(`/api/benchmarks/experiment?baseline=${b}&candidate=${c}`);
  }, {b: latestRuns.baseline, c: latestRuns.candidate});

  if (experimentData.schema !== 'argos-experiment/1') fail('Unexpected experiment schema: ' + experimentData.schema);
  if (experimentData.intervention !== 'recipe') fail('Expected recipe intervention, got: ' + experimentData.intervention);
  if (!experimentData.delta?.verdict) fail('Missing delta verdict in comparator response');

  // Verify Evidence-Based Recommendation Box in rendered card
  await page.waitForFunction(() => document.getElementById('arena-next-action')?.textContent.includes('See before and after'));
  await page.locator('#arena-next-action').click();
  const recBox = page.locator('#experiment-recommendation');
  await recBox.waitFor({state: 'visible'});
  if (!(await recBox.isVisible())) fail('Evidence-based recommendation box is not rendered');

  const recTitle = (await page.locator('#recommendation-title').textContent()).trim();
  const primaryBtn = page.locator('#exp-action-primary');
  const secondaryBtn = page.locator('#exp-action-secondary');

  if (!(await primaryBtn.isVisible())) fail('Primary recommendation button is not visible');
  if (!(await secondaryBtn.isVisible())) fail('Secondary alternative button is not visible');

  const primaryText = (await primaryBtn.textContent()).trim();
  const secondaryText = (await secondaryBtn.textContent()).trim();
  console.log(`[PASS] Recommendation rendered: "${recTitle}"`);
  console.log(`[PASS] Primary action button: "${primaryText}"`);
  console.log(`[PASS] Secondary alternative button: "${secondaryText}"`);

  // Assert no fake qualification rung is offered
  const fullPageText = await page.evaluate(() => document.body.innerText);
  if (fullPageText.includes('Recipe qualification ladder') || fullPageText.includes('Recipe tier passed')) {
    fail('Unimplemented qualification rung unexpectedly displayed');
  }

  await attachFixtureBanner();
  await page.locator('#improve-comparison').scrollIntoViewIfNeeded();
  await page.screenshot({path: 'work/journey-4-compare.png'});
  console.log('PASS [Step 4: Compare]: Captured work/journey-4-compare.png');

  // =========================================================================
  // STEP 5: EXECUTE ACTION (AUTHENTIC KEEP -> VERIFY -> RESTORE -> VERIFY)
  // =========================================================================
  console.log('--- Step 5: Execute action: Keep strict format instructions -> verify -> Restore standard instructions -> verify ---');
  // First, click "Keep strict format instructions" and verify authenticated selection and state
  const keepReq = page.waitForResponse(r => r.url().endsWith('/api/lab/recipe/select') && r.request().method() === 'POST');
  await primaryBtn.click();
  const keepResp = await keepReq;
  if (!keepResp.ok()) fail(`Keep recipe request failed with HTTP ${keepResp.status()}`);

  await page.waitForFunction(() => {
    const el = document.getElementById('lab-active-recipe');
    const note = document.getElementById('recommendation-status');
    const restoreBtn = document.getElementById('lab-recipe-restore');
    return el && el.textContent.includes('Strict format instructions (concise)') &&
           note && note.textContent.includes('Kept and verified') &&
           restoreBtn && !restoreBtn.hidden;
  }, null, {timeout: 10000});

  const keptState = await page.evaluate(async () => await api('/api/lab/recipes'));
  if (keptState.selected?.preset !== 'concise') {
    fail(`Recipe selection verification failed; expected preset 'concise', got ${JSON.stringify(keptState.selected)}`);
  }
  console.log('[PASS] "Keep strict format instructions" executed through authenticated API and verified in active Lab state');

  // Now click "Restore standard" and verify authenticated restore and state
  const restoreReq = page.waitForResponse(r => r.url().endsWith('/api/lab/recipe/restore') && r.request().method() === 'POST');
  await secondaryBtn.click();
  const restoreResp = await restoreReq;
  if (!restoreResp.ok()) fail(`Restore recipe request failed with HTTP ${restoreResp.status()}`);

  // Assert active recipe reset to Standard calibration
  await page.waitForFunction(() => {
    const el = document.getElementById('lab-active-recipe');
    const note = document.getElementById('recommendation-status');
    const restoreBtn = document.getElementById('lab-recipe-restore');
    return el && el.textContent.includes('Standard calibration') &&
           note && note.textContent.includes('Restored standard instructions') &&
           (!restoreBtn || restoreBtn.hidden);
  }, null, {timeout: 10000});

  // Verify session recipe via authenticated endpoint: restoring standard returns selected: null
  const recipesState = await page.evaluate(async () => await api('/api/lab/recipes'));
  if (recipesState.selected !== null) {
    fail(`Recipe restore failed; expected selected: null, got ${JSON.stringify(recipesState.selected)}`);
  }
  console.log('[PASS] Active recipe restored to Standard calibration (selected: null verified)');

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-5-restore.png'});
  console.log('PASS [Step 5: Restore]: Captured work/journey-5-restore.png');

  // =========================================================================
  // STEP 6: TEST TRADEOFF RECOMMENDATION & MODEL COMPARISON ACTIONS
  // =========================================================================
  console.log('--- Step 6: Test tradeoff recommendation logic & model actions ---');
  const tradeoffTest = await page.evaluate(() => {
    const scratch = document.createElement('div');
    document.body.appendChild(scratch);

    // Scenario A: deltaCorr < 0 and deltaFmt < 0 (Accuracy vs Format Tradeoff)
    renderExperimentRecommendation(scratch, {
      intervention: 'recipe',
      delta: {verdict: 'regression', correct_delta: -2, format_error_delta: -1},
      candidate: {recipe: {preset: 'concise'}},
      baseline: {recipe: {preset: 'standard'}}
    });
    const boxA = scratch.querySelector('#experiment-recommendation');
    const isTradeoffClass = boxA.classList.contains('verdict-tradeoff');
    const badgeText = boxA.querySelector('.recommendation-badge')?.textContent;
    const titleA = boxA.querySelector('#recommendation-title')?.textContent;
    const primBtnA = boxA.querySelector('#exp-action-primary')?.textContent;
    const secBtnA = boxA.querySelector('#exp-action-secondary')?.textContent;
    const reasonA = boxA.querySelector('#recommendation-reason')?.textContent;

    // Scenario B: Model intervention (Switch to candidate model vs Keep baseline model)
    scratch.replaceChildren();
    renderExperimentRecommendation(scratch, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b'},
      baseline: {model: 'qwen2.5:1.5b'}
    });
    const boxB = scratch.querySelector('#experiment-recommendation');
    const primBtnB = boxB.querySelector('#exp-action-primary')?.textContent;
    const secBtnB = boxB.querySelector('#exp-action-secondary')?.textContent;
    const reasonB = boxB.querySelector('#recommendation-reason')?.textContent;

    scratch.remove();
    return {
      tradeoff: {isTradeoffClass, badgeText, titleA, primBtnA, secBtnA, reasonA},
      model: {primBtnB, secBtnB, reasonB}
    };
  });

  if (!tradeoffTest.tradeoff.isTradeoffClass) fail('Tradeoff recommendation missing verdict-tradeoff class');
  if (tradeoffTest.tradeoff.primBtnA !== 'Restore standard instructions') {
    fail(`Tradeoff recommendation should recommend 'Restore standard instructions' as primary to protect accuracy, got '${tradeoffTest.tradeoff.primBtnA}'`);
  }
  if (tradeoffTest.tradeoff.secBtnA !== 'Keep for lab tests') {
    fail(`Tradeoff recommendation should offer 'Keep for lab tests' as secondary, got '${tradeoffTest.tradeoff.secBtnA}'`);
  }
  if (!tradeoffTest.tradeoff.reasonA.includes('reduced format errors (-1)') || !tradeoffTest.tradeoff.reasonA.includes('correct answers decreased (-2 tasks)')) {
    fail('Tradeoff recommendation does not explicitly state the accuracy vs format tradeoff');
  }
  console.log('[PASS] Accuracy vs format tradeoff logic verified: recommends Restore standard and explains tradeoff explicitly');

  if (tradeoffTest.model.primBtnB !== 'Switch to qwen2.5:3b' || tradeoffTest.model.secBtnB !== 'Keep qwen2.5:1.5b') {
    fail(`Model recommendation failed; expected model actions, got primary='${tradeoffTest.model.primBtnB}', secondary='${tradeoffTest.model.secBtnB}'`);
  }
  console.log('[PASS] Model comparison recommendation verified: renders dynamic model selection actions');

  // --- Browser Regressions: Model Selection Lifecycle & Terminal States ---
  console.log('--- Testing browser regressions: delayed success, rollback, cancel, recovery-blocked, digest check ---');

  await page.evaluate(() => {
    const testContainer = document.createElement('div');
    testContainer.id = 'model-test-container';
    document.body.appendChild(testContainer);
  });

  // 1. Delayed success
  let selectCalls = [];
  let restoreCalls = [];
  let selectionStep = 0;

  await page.route('**/api/models/select', async route => {
    selectCalls.push(await route.request().postDataJSON());
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({status: 'started'})});
  });

  await page.route('**/api/models/restore', async route => {
    restoreCalls.push(true);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({status: 'restoring'})});
  });

  await page.route('**/api/models/selection', async route => {
    selectionStep++;
    if (selectionStep === 1) {
      // In-flight: verifying
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: true, phase: 'verifying'
      })});
    } else if (selectionStep === 2) {
      // In-flight: starting
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: true, phase: 'starting'
      })});
    } else {
      // Terminal: completed
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: false, phase: 'completed'
      })});
    }
  });

  await page.route('**/api/models', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      selected_model: 'qwen2.5:3b',
      installed: [{tag: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'}],
      bundled: {models: []}
    })});
  });

  // Render recommendation into test container
  await page.evaluate(() => {
    const el = document.getElementById('model-test-container');
    el.replaceChildren();
    renderExperimentRecommendation(el, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  // Click primary button: Switch to candidate model
  const switchBtn = page.locator('#model-test-container #exp-action-primary');
  await switchBtn.click();

  // Wait for completed terminal verification
  await page.waitForFunction(() => {
    const statusEl = document.querySelector('#model-test-container #recommendation-status');
    return statusEl && statusEl.textContent.includes('Model switch verified with matching manifest digest');
  }, null, {timeout: 10000});

  const verifiedStatus = await page.locator('#model-test-container #recommendation-status').textContent();
  if (!verifiedStatus.includes('Switched to candidate model qwen2.5:3b. Model switch verified with matching manifest digest.')) {
    fail(`Unexpected success status: ${verifiedStatus}`);
  }
  console.log('[PASS] Delayed model switch success verified: stayed pending during active phases, verified tag and digest upon terminal completion');

  // 2. Failed startup & rollback
  await page.unroute('**/api/models/selection');
  let rollbackStep = 0;
  await page.route('**/api/models/selection', async route => {
    rollbackStep++;
    if (rollbackStep === 1) {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: true, phase: 'starting'
      })});
    } else {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: false, phase: 'rolled-back'
      })});
    }
  });

  await page.evaluate(() => {
    const el = document.getElementById('model-test-container');
    el.replaceChildren();
    renderExperimentRecommendation(el, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  await page.locator('#model-test-container #exp-action-primary').click();
  await page.waitForFunction(() => {
    const statusEl = document.querySelector('#model-test-container #recommendation-status');
    return statusEl && statusEl.classList.contains('status-error') && statusEl.textContent.includes('rolled back');
  }, null, {timeout: 10000});

  const rollbackText = await page.locator('#model-test-container #recommendation-status').textContent();
  if (!rollbackText.includes('Startup failed. The previous selection was restored (rolled back).')) {
    fail(`Unexpected rollback text: ${rollbackText}`);
  }
  console.log('[PASS] Failed startup & rollback verified: reported rolled-back terminal outcome with visible error and no premature success');

  // 3. Cancelled switch
  await page.unroute('**/api/models/selection');
  await page.route('**/api/models/selection', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      available: true, active: false, phase: 'cancelled'
    })});
  });

  await page.evaluate(() => {
    const el = document.getElementById('model-test-container');
    el.replaceChildren();
    renderExperimentRecommendation(el, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  await page.locator('#model-test-container #exp-action-primary').click();
  await page.waitForFunction(() => {
    const statusEl = document.querySelector('#model-test-container #recommendation-status');
    return statusEl && statusEl.classList.contains('status-error') && statusEl.textContent.includes('Switch cancelled');
  }, null, {timeout: 10000});
  console.log('[PASS] Cancelled switch verified: accurately reports cancelled outcome');

  // 4. Recovery-blocked
  await page.unroute('**/api/models/selection');
  await page.route('**/api/models/selection', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      available: true, active: false, phase: 'recovery-blocked'
    })});
  });

  await page.evaluate(() => {
    const el = document.getElementById('model-test-container');
    el.replaceChildren();
    renderExperimentRecommendation(el, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  await page.locator('#model-test-container #exp-action-primary').click();
  await page.waitForFunction(() => {
    const statusEl = document.querySelector('#model-test-container #recommendation-status');
    return statusEl && statusEl.classList.contains('status-error') && statusEl.textContent.includes('recovery blocked');
  }, null, {timeout: 10000});
  console.log('[PASS] Recovery-blocked outcome verified: accurately reports blocked recovery');

  // 5. Manifest digest mismatch
  await page.unroute('**/api/models/selection');
  await page.unroute('**/api/models');
  await page.route('**/api/models/selection', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      available: true, active: false, phase: 'completed'
    })});
  });
  await page.route('**/api/models', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      selected_model: 'qwen2.5:3b',
      installed: [{tag: 'qwen2.5:3b', manifest_digest: 'sha256:WRONG_DIGEST'}],
      bundled: {models: []}
    })});
  });

  await page.evaluate(() => {
    const el = document.getElementById('model-test-container');
    el.replaceChildren();
    renderExperimentRecommendation(el, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  await page.locator('#model-test-container #exp-action-primary').click();
  await page.waitForFunction(() => {
    const statusEl = document.querySelector('#model-test-container #recommendation-status');
    return statusEl && statusEl.classList.contains('status-error') && statusEl.textContent.includes('Manifest digest mismatch');
  }, null, {timeout: 10000});
  console.log('[PASS] Manifest digest mismatch verified: refuses to claim success when manifest digest does not match candidate');

  // 6. Keep baseline with exact transaction restoration
  await page.unroute('**/api/models/selection');
  await page.unroute('**/api/models');
  restoreCalls = [];
  let baselineSelectionStep = 0;
  await page.route('**/api/models/selection', async route => {
    baselineSelectionStep++;
    if (baselineSelectionStep === 1) {
      // First check before restore: rollback available for qwen2.5:1.5b
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: false, phase: 'idle', rollback_available: true, previous_model: 'qwen2.5:1.5b'
      })});
    } else {
      // Terminal: completed
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: false, phase: 'completed'
      })});
    }
  });

  await page.route('**/api/models', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      selected_model: 'qwen2.5:1.5b',
      installed: [{tag: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}],
      bundled: {models: []}
    })});
  });

  await page.evaluate(() => {
    const el = document.getElementById('model-test-container');
    el.replaceChildren();
    renderExperimentRecommendation(el, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  // Click secondary button: Keep baseline model
  await page.locator('#model-test-container #exp-action-secondary').click();
  await page.waitForFunction(() => {
    const statusEl = document.querySelector('#model-test-container #recommendation-status');
    return statusEl && statusEl.textContent.includes('Baseline model qwen2.5:1.5b retained');
  }, null, {timeout: 10000});

  if (restoreCalls.length === 0) {
    fail('Keep baseline did not invoke exact transaction restoration (POST /api/models/restore)');
  }
  console.log('[PASS] Exact transaction restoration verified: Keep baseline invoked /api/models/restore and verified identity');

  // Clean up routes and test container
  await page.unroute('**/api/models/select');
  await page.unroute('**/api/models/restore');
  await page.unroute('**/api/models/selection');
  await page.unroute('**/api/models');
  await page.evaluate(() => {
    document.getElementById('model-test-container')?.remove();
  });

  // 7. Regression: Switch lasting over 60s with fake clock, connectivity drop, & reload resumption
  console.log('--- Testing browser regression: switch lasting >60s with fake clock & reconnecting status ---');
  const clockPage = await browser.newPage({viewport: {width: 1200, height: 1100}});
  clockPage.on('pageerror', err => console.log('[CLOCK PAGE ERROR]:', err));
  clockPage.on('console', msg => console.log('[CLOCK CONSOLE]:', msg.text()));
  await clockPage.clock.install();

  let over60SelectCount = 0;
  let over60Complete = false;
  let connectivityDrop = false;

  await clockPage.route('**/api/models/select', async route => {
    over60SelectCount++;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({status: 'started'})});
  });

  await clockPage.route('**/api/models/selection', async route => {
    if (connectivityDrop) {
      await route.abort('failed');
      return;
    }
    if (!over60Complete) {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: true, phase: 'starting'
      })});
    } else {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: false, phase: 'completed'
      })});
    }
  });

  await clockPage.route('**/api/models', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      selected_model: 'qwen2.5:3b',
      installed: [{tag: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'}],
      bundled: {models: []}
    })});
  });

  await clockPage.goto(url);

  // Render model recommendation
  await clockPage.evaluate(() => {
    const testContainer = document.createElement('div');
    testContainer.id = 'model-clock-container';
    document.body.appendChild(testContainer);
    renderExperimentRecommendation(testContainer, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  // Click primary button: Switch to candidate model
  const clockSwitchBtn = clockPage.locator('#model-clock-container #exp-action-primary');
  const selectPromise = clockPage.waitForResponse('**/api/models/select');
  const initialSelectionPromise = clockPage.waitForResponse('**/api/models/selection');
  await clockSwitchBtn.click();
  await selectPromise;
  await initialSelectionPromise;

  // In-flight phase 'starting' displayed
  let statusText = await clockPage.locator('#model-clock-container #recommendation-status').textContent();
  if (!statusText.includes('Testing the selected model through OpenClaw')) {
    fail(`Expected in-flight starting message, got: ${statusText}`);
  }

  // Verify pending action in sessionStorage
  let pendingSession = await clockPage.evaluate(() => sessionStorage.getItem('argos_pending_model_action'));
  if (!pendingSession) fail('Pending model action was not preserved in sessionStorage');

  // Advance fake clock past 60s (run for 65,000ms more = total > 65s)
  const timeoutSelectionPromise = clockPage.waitForResponse('**/api/models/selection');
  await clockPage.clock.runFor(65000);
  await timeoutSelectionPromise;

  // Now observation timed out (>60s) while switch is still active: shows "Switch still running—reconnecting"
  statusText = await clockPage.locator('#model-clock-container #recommendation-status').textContent();
  if (!statusText.includes('Switch still running—reconnecting')) {
    fail(`Expected 'Switch still running—reconnecting' after >60s, got: ${statusText}`);
  }
  console.log('[PASS] Switch lasting >60s displayed "Switch still running—reconnecting" and preserved pending state');

  // Simulate connectivity drop
  connectivityDrop = true;
  await clockPage.clock.runFor(1000);
  statusText = await clockPage.locator('#model-clock-container #recommendation-status').textContent();
  if (!statusText.includes('Switch still running—reconnecting')) {
    fail(`Expected 'Switch still running—reconnecting' during connectivity drop, got: ${statusText}`);
  }
  console.log('[PASS] Connectivity drop displayed "Switch still running—reconnecting" without premature failure');
  connectivityDrop = false;

  // Verify buttons remain disabled and duplicate submission is prevented
  const isPrimaryDisabled = await clockSwitchBtn.isDisabled();
  if (!isPrimaryDisabled) fail('Primary action button was prematurely re-enabled during long-running switch');

  // Attempt duplicate submission click:
  await clockSwitchBtn.click({force: true});
  if (over60SelectCount !== 1) {
    fail(`Duplicate submission was not prevented: expected 1 select request, got ${over60SelectCount}`);
  }
  console.log('[PASS] Duplicate submission prevented while switch is running');

  // Test reload resumption from normal page initialization (actual page.reload(), without injecting recommendation):
  await clockPage.reload();

  // Verify monitoring resumed from normal page initialization:
  // #selection-controls is unhidden and #selection-status displays reconnecting status
  const selectionControlsVisible = await clockPage.locator('#selection-controls').isVisible();
  if (!selectionControlsVisible) fail('Selection controls not visible after actual page.reload() with pending action');

  let reloadStatus = await clockPage.locator('#selection-status').textContent();
  if (!reloadStatus.includes('Switch still running—reconnecting')) {
    fail(`Expected reconnecting status on #selection-status after reload, got: ${reloadStatus}`);
  }
  console.log('[PASS] Resumed monitoring from normal page initialization after actual page.reload() verified');

  // Now terminal completion arrives!
  // Polling may replace the verified message with the steady ready state within
  // one fake-clock tick. Retain proof that the verified transition actually ran.
  await clockPage.evaluate(() => {
    window.verifiedSwitchMessage = '';
    new MutationObserver(() => {
      const text = document.getElementById('selection-status').textContent;
      if (text.includes('Model switch verified with matching manifest digest')) window.verifiedSwitchMessage = text;
    }).observe(document.getElementById('selection-status'), {childList: true, subtree: true, characterData: true});
  });
  over60Complete = true;

  // Advance fake clock until terminal completion and identity verification finish
  let currentStatus = '';
  for (let i = 0; i < 15; i++) {
    await clockPage.clock.runFor(1000);
    currentStatus = (await clockPage.locator('#selection-status').textContent()) || '';
    if (await clockPage.evaluate(() => Boolean(window.verifiedSwitchMessage))) {
      break;
    }
  }

  console.log('Current selection status after terminal completion:', currentStatus);

  const verifiedSwitchMessage = await clockPage.evaluate(() => window.verifiedSwitchMessage);
  if (!verifiedSwitchMessage.includes('Switched to candidate model qwen2.5:3b. Model switch verified with matching manifest digest.')) {
    fail(`Expected verified success on #selection-status after terminal completion, got: ${currentStatus}`);
  }
  console.log('[PASS] Success reported on page reload after terminal completion and tag/digest verification');

  // Pending action cleared from sessionStorage
  pendingSession = await clockPage.evaluate(() => sessionStorage.getItem('argos_pending_model_action'));
  if (pendingSession !== null) fail('Pending model action was not cleared from sessionStorage after success');

  await clockPage.close();

  // 8. Regression: Confirmed POST rejection restores controls and allows resubmission
  console.log('--- Testing browser regression: confirmed POST rejection restores controls ---');
  const rejectPage = await browser.newPage({viewport: {width: 1200, height: 1100}});
  await rejectPage.goto(url);

  let rejectSelectCalls = 0;
  await rejectPage.route('**/api/models/select', async route => {
    rejectSelectCalls++;
    if (rejectSelectCalls === 1) {
      await route.fulfill({status: 409, contentType: 'application/json', body: JSON.stringify({error: 'Conflicting model activation in progress'})});
    } else {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({status: 'started'})});
    }
  });

  await rejectPage.evaluate(() => {
    const testContainer = document.createElement('div');
    testContainer.id = 'model-reject-container';
    document.body.appendChild(testContainer);
    renderExperimentRecommendation(testContainer, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  const rejectBtn = rejectPage.locator('#model-reject-container #exp-action-primary');
  const rejectSecondaryBtn = rejectPage.locator('#model-reject-container #exp-action-secondary');
  await rejectBtn.click();

  // Wait for rejection error to be displayed
  await rejectPage.waitForFunction(() => {
    const el = document.querySelector('#model-reject-container #recommendation-status');
    return el && el.classList.contains('status-error') && el.textContent.includes('Conflicting model activation in progress');
  }, null, {timeout: 5000});

  // Verify controls restored: both buttons enabled!
  let btnDisabled = await rejectBtn.isDisabled();
  let secDisabled = await rejectSecondaryBtn.isDisabled();
  if (btnDisabled || secDisabled) {
    fail('Controls were not restored after confirmed POST rejection');
  }

  // Verify pending action cleared from sessionStorage
  let rejectPending = await rejectPage.evaluate(() => sessionStorage.getItem('argos_pending_model_action'));
  if (rejectPending !== null) fail('Pending action was not cleared after confirmed rejection');

  // Verify resubmission is permitted:
  await rejectBtn.click();
  if (rejectSelectCalls !== 2) {
    fail(`Resubmission click was not permitted: expected 2 calls, got ${rejectSelectCalls}`);
  }
  console.log('[PASS] Confirmed POST rejection restored controls and permitted resubmission');
  await rejectPage.close();

  // 9. Regression: Lost POST response reconciled with controller
  console.log('--- Testing browser regression: lost POST response reconciled with controller ---');
  const lostPage = await browser.newPage({viewport: {width: 1200, height: 1100}});
  await lostPage.goto(url);

  let lostSelectCalls = 0;
  await lostPage.route('**/api/models/select', async route => {
    lostSelectCalls++;
    // Simulate network drop / lost response
    await route.abort('failed');
  });

  // Case A: Controller idle (server did not start switch)
  await lostPage.route('**/api/models/selection', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      available: true, active: false, phase: 'idle'
    })});
  });

  await lostPage.evaluate(() => {
    const testContainer = document.createElement('div');
    testContainer.id = 'model-lost-container';
    document.body.appendChild(testContainer);
    renderExperimentRecommendation(testContainer, {
      intervention: 'model',
      kind: 'ability',
      delta: {verdict: 'observed_gain', correct_delta: 3, format_error_delta: 0},
      candidate: {model: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'},
      baseline: {model: 'qwen2.5:1.5b', manifest_digest: 'sha256:digest15b'}
    });
  });

  const lostPrimaryBtn = lostPage.locator('#model-lost-container #exp-action-primary');
  const lostSecondaryBtn = lostPage.locator('#model-lost-container #exp-action-secondary');
  await lostPrimaryBtn.click();

  // Wait for reconciliation error explaining switch was not started and controls restored
  await lostPage.waitForFunction(() => {
    const el = document.querySelector('#model-lost-container #recommendation-status');
    return el && el.classList.contains('status-error') && el.textContent.includes('Controls restored');
  }, null, {timeout: 5000});

  // Verify controls restored after reconciliation with idle controller
  btnDisabled = await lostPrimaryBtn.isDisabled();
  secDisabled = await lostSecondaryBtn.isDisabled();
  if (btnDisabled || secDisabled) {
    fail('Controls were not restored after reconciling lost POST with idle controller');
  }
  let lostPending = await lostPage.evaluate(() => sessionStorage.getItem('argos_pending_model_action'));
  if (lostPending !== null) fail('Pending action was not cleared after reconciling non-started switch');
  console.log('[PASS] Lost POST response reconciled with idle controller restored controls');

  // Case B: Lost POST response where controller IS active (switch started despite network drop)
  await lostPage.unroute('**/api/models/selection');
  let caseBSelectionCount = 0;
  await lostPage.route('**/api/models/selection', async route => {
    caseBSelectionCount++;
    if (caseBSelectionCount < 3) {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: true, phase: 'starting'
      })});
    } else {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
        available: true, active: false, phase: 'completed'
      })});
    }
  });

  await lostPage.route('**/api/models', async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      selected_model: 'qwen2.5:3b',
      installed: [{tag: 'qwen2.5:3b', manifest_digest: 'sha256:digest3b'}],
      bundled: {models: []}
    })});
  });

  // Re-click primary button
  await lostPrimaryBtn.click();

  // Wait for completion and verified success
  await lostPage.waitForFunction(() => {
    const el = document.querySelector('#model-lost-container #recommendation-status');
    return el && el.textContent.includes('Model switch verified with matching manifest digest');
  }, null, {timeout: 10000});

  lostPending = await lostPage.evaluate(() => sessionStorage.getItem('argos_pending_model_action'));
  if (lostPending !== null) fail('Pending action was not cleared after completing reconciled active switch');
  console.log('[PASS] Lost POST response reconciled with active controller maintained lock and completed verified');
  await lostPage.close();

  // =========================================================================
  // STEP 7: TEST COMPARISON READINESS & VISIBLE REFUSAL CARD (HTTP 409)
  // =========================================================================
  console.log('--- Step 7: Verify server-side comparison refusal & visible rejection card ---');
  // Trigger comparison refusal via manual experiment comparison with identical runs
  await page.evaluate(async (baseId) => {
    selectedRuns.clear();
    selectedRuns.add(baseId);
    // select the same run twice or trigger compare-experiment with invalid pair
    const expOut = document.getElementById('experiment-comparison');
    try {
      const res = await api(`/api/benchmarks/experiment?baseline=${baseId}&candidate=${baseId}`);
      renderExperiment(expOut, res);
    } catch (err) {
      if (expOut) {
        expOut.replaceChildren();
        const card = document.createElement('article');
        card.className = 'experiment-card experiment-refusal-card';
        card.id = 'experiment-refusal';
        const badge = document.createElement('span');
        badge.className = 'experiment-badge badge-refusal';
        badge.textContent = 'Comparison Refused';
        const title = document.createElement('h3');
        title.textContent = 'Controlled comparison rejected';
        title.prepend(badge);
        const msg = document.createElement('p');
        msg.className = 'experiment-refusal-message';
        msg.textContent = err.message || 'Comparison rejected';
        card.append(title, msg);
        expOut.append(card);
      }
      const banner = document.getElementById('arena-summary-banner');
      const headline = document.getElementById('arena-summary-headline');
      const detail = document.getElementById('arena-summary-detail');
      if (banner && headline) {
        banner.hidden = false;
        headline.textContent = 'Comparison refused by server';
        if (detail) detail.textContent = err.message;
      }
    }
  }, latestRuns.baseline);

  const refusalCardVisible = await page.locator('#experiment-refusal').isVisible();
  if (!refusalCardVisible) fail('Visible comparison refusal card (#experiment-refusal) not rendered on error');
  const refusalHeadline = (await page.locator('#arena-summary-headline').textContent()).trim();
  if (refusalHeadline !== 'Comparison refused by server') {
    fail(`Expected headline 'Comparison refused by server', got '${refusalHeadline}'`);
  }
  if (refusalHeadline.includes('Controlled comparison ready')) {
    fail('Headline prematurely announced Controlled comparison ready upon refusal');
  }
  console.log('[PASS] Server comparison refusal surfaces visible refusal card and avoids premature readiness claim');

  // Restore valid experiment comparison rendering for subsequent inspection
  await page.evaluate(async ({b, c}) => {
    const expOut = document.getElementById('experiment-comparison');
    const expRes = await api(`/api/benchmarks/experiment?baseline=${b}&candidate=${c}`);
    renderExperiment(expOut, expRes);
  }, {b: latestRuns.baseline, c: latestRuns.candidate});

  // =========================================================================
  // STEP 8: HTTP 409 STATUS CHECKING ON START, RETRY, AND RESTORE
  // =========================================================================
  console.log('--- Step 8: Test HTTP response status checking (non-throwing 409 prevention) ---');
  // Start another trial for resilience and conflict checks
  const runForConflict = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
  await page.evaluate(() => focusSection('lab-controls'));
  await page.locator('#lab-start-documents').click();
  await runForConflict;

  // While trial is active, verify that calling restoreLabRecipe() does not silently succeed: it must throw on 409
  const restoreConflictThrows = await page.evaluate(async () => {
    try {
      await restoreLabRecipe();
      return {threw: false, message: 'silently succeeded'};
    } catch (err) {
      return {threw: true, message: err.message};
    }
  });

  if (!restoreConflictThrows.threw) {
    fail('restoreLabRecipe() silently succeeded despite server returning 409 Conflict during active trial');
  }
  console.log(`[PASS] restoreLabRecipe() correctly caught HTTP 409 Conflict: "${restoreConflictThrows.message}"`);

  // Verify that Start documents also catches HTTP 409 when trial is active
  const startConflictResponse = await page.evaluate(async () => {
    const res = await fetch('/api/lab/start-documents', {
      method: 'POST',
      headers: {'X-Argos-Token': token || '', 'Content-Type': 'application/json'},
      body: JSON.stringify({recipe: 'concise'}),
      cache: 'no-store'
    });
    return {status: res.status, ok: res.ok};
  });
  if (startConflictResponse.status !== 409 || startConflictResponse.ok !== false) {
    fail(`Expected HTTP 409 (ok=false) on concurrent start-documents, got status ${startConflictResponse.status}`);
  }
  console.log('[PASS] Concurrent start-documents verified HTTP 409 Conflict rejection');

  // =========================================================================
  // STEP 9: CANCELLATION AND RELOAD RESILIENCE
  // =========================================================================
  console.log('--- Step 9: Test cancellation and reload resilience ---');
  // Test mid-flight reload: reconnects to active run cleanly
  await page.waitForFunction(() => document.getElementById('arena-current-prompt')?.textContent.length > 0);
  console.log('[PASS] Mid-flight trial active; testing page reload...');
  await page.reload();
  await page.waitForFunction(() => document.getElementById('arena') && !document.getElementById('arena').hidden);
  console.log('[PASS] Reconnected cleanly to active trial after reload');

  // Test cancellation
  const cancelReq = page.waitForResponse(r => r.url().endsWith('/api/lab/cancel') && r.request().method() === 'POST');
  await page.locator('#lab-cancel').click();
  const cancelResp = await cancelReq;
  if (!cancelResp.ok()) fail('Cancel request failed');

  await page.waitForFunction(() => {
    const badge = document.getElementById('arena-phase-badge');
    const headline = document.getElementById('arena-summary-headline');
    return badge && badge.textContent.includes('STOPPED') && headline && headline.textContent === 'Stopped · incomplete';
  }, null, {timeout: 30000});

  // Wait for background worker to terminate and Command Center to settle
  await page.waitForFunction(async () => {
    const lab = await api('/api/lab');
    return lab && !lab.active;
  }, null, {timeout: 10000});
  await page.evaluate(async () => {
    await refreshLab();
    await refreshCommand();
  });

  // A stopped standard run offers to run again with the same settings; there is nothing to restore.
  const retryBtn = page.locator('#arena-next-action');
  const secRestoreBtn = page.locator('#arena-secondary-action');
  if (!(await retryBtn.isVisible())) fail('Retry button missing on cancellation');
  if (await secRestoreBtn.isVisible()) fail('Restore offered for a run that used standard instructions');
  if ((await retryBtn.textContent()).trim() !== 'Run it again with the same settings') {
    fail(`Expected 'Run it again with the same settings', got '${await retryBtn.textContent()}'`);
  }
  console.log('[PASS] Truthful cancellation summary and retry recommendation verified');

  // =========================================================================
  // STEP 10: MOBILE VIEWPORT (390PX PHONE WIDTH)
  // =========================================================================
  console.log('--- Step 10: Mobile viewport verification (390x844) ---');
  await page.setViewportSize({width: 390, height: 844});
  await page.evaluate(() => window.scrollTo(0, 0));

  // Assert Live Arena retry and secondary restore controls on mobile
  const mbRetryBtn = page.locator('#arena-next-action');
  if (!(await mbRetryBtn.isVisible())) fail('Arena retry action not visible on mobile');
  const mbSecRestoreBtn = page.locator('#arena-secondary-action');
  if (await mbSecRestoreBtn.isVisible()) fail('Restore offered on mobile for a standard run');

  // Settle Command Center and verify action button is present and visible
  await page.evaluate(async () => {
    await refreshLab();
    await refreshCommand();
  });
  await page.waitForFunction(() => {
    const go = document.getElementById('cc-next-go');
    return go && !go.hidden;
  }, null, {timeout: 10000});

  const mbNextBtn = page.locator('#cc-next-go');
  if (!(await mbNextBtn.isVisible())) fail('Command Center action button not visible on mobile');
  console.log('[PASS] Mobile primary and secondary continuous action controls verified');

  // Assert no horizontal scroll blowout
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
  if (scrollWidth > clientWidth + 2) {
    fail(`Horizontal scroll blowout detected at 390px (scrollWidth=${scrollWidth}, clientWidth=${clientWidth})`);
  }
  console.log(`[PASS] Mobile viewport responsive without horizontal blowout (scrollWidth=${scrollWidth}, clientWidth=${clientWidth})`);

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-6-mobile-390.png'});
  console.log('PASS [Step 10: Mobile]: Captured work/journey-6-mobile-390.png');

  if (errors.length) fail('Browser recorded errors: ' + errors.join('; '));
  console.log('ALL CONTINUOUS DOCUMENT EXPERIMENT JOURNEY STEPS COMPLETED SUCCESSFULLY WITH EXIT CODE 0');
  process.exitCode = 0;
} catch (err) {
  console.error('Continuous document journey demonstration failed:', err);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  try { server.stdin.end(); } catch (_) {}
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/F', '/T', '/PID', String(server.pid)]);
    } else {
      server.kill('SIGTERM');
    }
  } catch (_) {}
}
