// Demonstrate the complete continuous document mission experiment flow:
// 1. Start through "Start: Read this brief" (#cc-next-go).
// 2. Watch live arena streaming an actual challenge answer (passage, tokens, scored receipts).
// 3. Baseline completion retains baseline run ID; recipe modal opens with OpenClaw personality protection notice.
// 4. Candidate retest runs with concise recipe; automatically pairs with baseline run ID and calls server comparator.
// 5. Evidence-based recommendation rendered (primary Keep trial recipe / secondary Restore standard, or vice versa).
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

  // Wait for baseline document trial to complete and baseline run ID to be retained
  await page.waitForFunction(() => {
    const badge = document.getElementById('arena-phase-badge');
    const status = document.getElementById('lab-status');
    const baselineSaved = (badge && badge.textContent.includes('COMPLETED')) || (status && status.textContent.includes('Document trial saved'));
    const idRetained = sessionStorage.getItem('argos_baseline_doc_run_id') !== null;
    return baselineSaved && idRetained;
  }, null, {timeout: 90000});

  const retainedBaselineId = await page.evaluate(() => sessionStorage.getItem('argos_baseline_doc_run_id'));
  if (!retainedBaselineId) fail('Baseline document run ID was not retained in session storage');
  console.log(`[PASS] Retained baseline run ID: ${retainedBaselineId}`);

  // =========================================================================
  // STEP 3: OPEN RECIPE MODAL & VERIFY PERSONALITY PROTECTION
  // =========================================================================
  console.log('--- Step 3: Open recipe experiment modal ---');
  const changeBtn = page.locator('#receipt-change');
  await changeBtn.waitFor({state: 'visible'});
  await changeBtn.click();

  await page.waitForFunction(() => document.getElementById('recipe-modal')?.open);
  const modalText = await page.locator('#recipe-modal').textContent();

  // Assert OpenClaw assistant personality protection notice is explicit
  if (!modalText.includes('Assistant protection (No personality or weight change)')) {
    fail('Recipe modal lacks OpenClaw assistant protection title');
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
    const card = document.querySelector('#experiment-comparison .experiment-card');
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
  const recBox = page.locator('#experiment-recommendation');
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
  await page.locator('#experiment-comparison').scrollIntoViewIfNeeded();
  await page.screenshot({path: 'work/journey-4-compare.png'});
  console.log('PASS [Step 4: Compare]: Captured work/journey-4-compare.png');

  // =========================================================================
  // STEP 5: EXECUTE ACTION (RESTORE STANDARD)
  // =========================================================================
  console.log('--- Step 5: Execute action (Restore standard) ---');
  // Secondary button is "Restore standard" when concise had observed gain
  const restoreBtn = secondaryText === 'Restore standard' ? secondaryBtn : primaryBtn;
  const restoreReq = page.waitForResponse(r => r.url().endsWith('/api/lab/recipe/restore') && r.request().method() === 'POST');
  await restoreBtn.click();
  const restoreResp = await restoreReq;
  if (!restoreResp.ok()) fail('Restore recipe request failed');

  // Assert active recipe reset to Standard calibration
  await page.waitForFunction(() => {
    const el = document.getElementById('lab-active-recipe');
    const note = document.getElementById('recommendation-status');
    return el && el.textContent.includes('Standard calibration') && note && note.textContent.includes('Restored standard calibration');
  }, null, {timeout: 10000});

  // Verify session recipe via authenticated endpoint: restoring standard returns selected: null
  const recipesState = await page.evaluate(async () => {
    return await api('/api/lab/recipes');
  });
  if (recipesState.selected !== null) {
    fail(`Recipe restore failed; expected selected: null, got ${JSON.stringify(recipesState.selected)}`);
  }
  console.log('[PASS] Active recipe restored to Standard calibration (selected: null verified)');

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-5-restore.png'});
  console.log('PASS [Step 5: Restore]: Captured work/journey-5-restore.png');

  // =========================================================================
  // STEP 6: CANCELLATION AND RELOAD RESILIENCE
  // =========================================================================
  console.log('--- Step 6: Test cancellation and reload resilience ---');
  // Start another trial for resilience checks
  const runForCancel = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
  await page.locator('#lab-start-documents').click();
  await runForCancel;

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

  // Assert cancellation banner offers primary Retry failed trial and secondary Restore standard
  const retryBtn = page.locator('#arena-next-action');
  const secRestoreBtn = page.locator('#arena-secondary-action');
  if (!(await retryBtn.isVisible())) fail('Retry button missing on cancellation');
  if (!(await secRestoreBtn.isVisible())) fail('Secondary restore button missing on cancellation');
  if ((await retryBtn.textContent()).trim() !== 'Retry failed trial') {
    fail(`Expected 'Retry failed trial', got '${await retryBtn.textContent()}'`);
  }
  console.log('[PASS] Truthful cancellation summary and retry recommendation verified');

  // =========================================================================
  // STEP 7: INCOMPATIBLE-PAIR REFUSAL (SERVER-SIDE VALIDATION)
  // =========================================================================
  console.log('--- Step 7: Verify server-side incompatible-pair refusal (HTTP 409) ---');
  const identicalRefusal = await page.evaluate(async (rid) => {
    try {
      const res = await fetch(`/api/benchmarks/experiment?baseline=${rid}&candidate=${rid}`, {headers: {'X-Argos-Token': token || ''}});
      const body = await res.json();
      return {status: res.status, error: body.error};
    } catch (e) {
      return {status: 0, error: e.message};
    }
  }, latestRuns.baseline);

  if (identicalRefusal.status !== 409) {
    fail(`Expected 409 Conflict for identical pair, got ${identicalRefusal.status}`);
  }
  if (!identicalRefusal.error?.includes('Choose distinct runs')) {
    fail(`Expected 'Choose distinct runs' error, got '${identicalRefusal.error}'`);
  }
  console.log(`[PASS] Server refused identical pair comparison: HTTP 409 "${identicalRefusal.error}"`);

  // =========================================================================
  // STEP 8: MOBILE VIEWPORT (390PX PHONE WIDTH)
  // =========================================================================
  console.log('--- Step 8: Mobile viewport verification (390x844) ---');
  await page.setViewportSize({width: 390, height: 844});
  await page.evaluate(() => window.scrollTo(0, 0));

  // Assert Live Arena retry and secondary restore controls on mobile
  const mbRetryBtn = page.locator('#arena-next-action');
  if (!(await mbRetryBtn.isVisible())) fail('Arena retry action not visible on mobile');
  const mbSecRestoreBtn = page.locator('#arena-secondary-action');
  if (!(await mbSecRestoreBtn.isVisible())) fail('Arena secondary restore action not visible on mobile');

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
  console.log('PASS [Step 8: Mobile]: Captured work/journey-6-mobile-390.png');

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
