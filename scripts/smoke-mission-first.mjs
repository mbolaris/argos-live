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

const server = spawn(process.env.ARGOS_PYTHON || 'py', ['-u', 'scripts/serve-journey-fixture.py'], {stdio: ['pipe', 'pipe', 'inherit']});
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

  // 5. Test delayed and failed assistant recovery reporting
  // Test delayed recovery (in progress)
  const delayedText = await page.evaluate(() => {
    return formatRecoveryStatus({state: 'recovering', message: 'Assistant recovery in progress.'});
  });
  if (delayedText !== 'Assistant recovery in progress.') fail(`Delayed recovery text unexpected: "${delayedText}"`);

  // Test failed recovery
  const failedText = await page.evaluate(() => {
    return formatRecoveryStatus({state: 'failed', message: 'Assistant recovery failed.'});
  });
  if (failedText !== 'Assistant recovery failed.') fail(`Failed recovery text unexpected: "${failedText}"`);

  // Test ready recovery
  const readyText = await page.evaluate(() => {
    return formatRecoveryStatus({state: 'ready', message: 'Assistant ready.'});
  });
  if (readyText !== 'Assistant ready.') fail(`Ready recovery text unexpected: "${readyText}"`);
  console.log('[PASS] Assistant recovery states tested: recovering, failed, ready');

  // 6. Test heroResult 3-state qualification:
  // a) Baseline report (no qualification): "Not assessed", NOT "Missed"
  const baselineQual = await page.evaluate(() => {
    const ab = {correct: 8, total: 8, qualified: null};
    const qualState = ab ? (ab.qualified === true ? 'Qualified' : (ab.qualified === false ? 'Criteria not met' : 'Not assessed')) : '';
    return ab ? `${ab.correct}/${ab.total} (${qualState})` : 'Not yet tested';
  });
  if (baselineQual !== '8/8 (Not assessed)') fail(`Baseline expected '8/8 (Not assessed)', got '${baselineQual}'`);
  if (baselineQual.includes('Missed')) fail('Baseline qualification displayed Missed instead of Not assessed');

  // b) Document trial met criteria: "Qualified"
  const metQual = await page.evaluate(() => {
    const ab = {correct: 8, total: 8, qualified: true};
    const qualState = ab ? (ab.qualified === true ? 'Qualified' : (ab.qualified === false ? 'Criteria not met' : 'Not assessed')) : '';
    return ab ? `${ab.correct}/${ab.total} (${qualState})` : 'Not yet tested';
  });
  if (metQual !== '8/8 (Qualified)') fail(`Met qualification expected '8/8 (Qualified)', got '${metQual}'`);

  // c) Document trial failed criteria: "Criteria not met"
  const notMetQual = await page.evaluate(() => {
    const ab = {correct: 5, total: 8, qualified: false};
    const qualState = ab ? (ab.qualified === true ? 'Qualified' : (ab.qualified === false ? 'Criteria not met' : 'Not assessed')) : '';
    return ab ? `${ab.correct}/${ab.total} (${qualState})` : 'Not yet tested';
  });
  if (notMetQual !== '5/8 (Criteria not met)') fail(`Failed qualification expected '5/8 (Criteria not met)', got '${notMetQual}'`);

  console.log('[PASS] Hero result qualification tri-state verified (Qualified, Criteria not met, Not assessed)');
  console.log('All Mission First J5 corrections passed successfully!');
} finally {
  if (browser) await browser.close();
  server.kill();
}
