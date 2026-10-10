// Simulated model fixture demonstration of the Proving Ground live arena UI:
// - Uses scripts/serve-journey-fixture.py (simulated model backend)
// - Validates BROWSER client behavior: streaming HUD, answer delta accumulation,
//   incremental scored receipts list, mid-test page reload reconnect, and cancellation UI.
// - NOTE: This validates browser UI behavior against a simulated backend.
//   It does NOT validate real local model streaming or physical cancellation.
//   The real-model check remains explicitly pending.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');

console.log('[SIMULATED MODEL FIXTURE] Starting serve-journey-fixture.py backend…');
const server = spawn(process.env.ARGOS_PYTHON || 'python3', ['-u', 'scripts/serve-journey-fixture.py'], {
  stdio: ['pipe', 'pipe', 'inherit']
});

let browser;
try {
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 20000);
    createInterface({ input: server.stdout }).once('line', line => {
      clearTimeout(timer);
      done(line.trim());
    });
    server.once('error', reject);
  });

  browser = await chromium.launch({ headless: true });

  // 1. Desktop Experience & Live Streaming (Browser UI validation with simulated backend)
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.goto(url);

  // Start the baseline trial
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled, null, { timeout: 30000 });
  await page.evaluate(() => focusSection('lab-controls'));
  await page.locator('#lab-start').click();

  // Wait for arena to display and start streaming
  await page.waitForFunction(() => {
    const arena = document.getElementById('arena');
    const stream = document.getElementById('arena-current-stream');
    return arena && !arena.hidden && stream && stream.textContent.length > 5;
  }, null, { timeout: 30000 });

  // Wait for at least 2 receipts to accumulate
  await page.waitForFunction(() => {
    const receipts = document.querySelectorAll('#arena-receipts-list .arena-receipt-row');
    return receipts.length >= 2;
  }, null, { timeout: 30000 });

  await page.locator('#arena').scrollIntoViewIfNeeded();
  await page.locator('#arena').screenshot({ path: 'work/arena-streaming-desktop.png' });
  console.log('CAPTURED: work/arena-streaming-desktop.png (simulated model fixture)');

  // Capture on 390px mobile viewport while active
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#arena').scrollIntoViewIfNeeded();
  await page.locator('#arena').screenshot({ path: 'work/arena-streaming-phone-390.png' });
  console.log('CAPTURED: work/arena-streaming-phone-390.png (simulated model fixture)');

  // 2. Demonstrate Reload / Reconnect Mid-Test (Browser client reconnect behavior)
  console.log('DEMONSTRATING: Browser page reload & reconnect mid-test…');
  await page.reload();
  await page.waitForFunction(() => {
    const arena = document.getElementById('arena');
    const badge = document.getElementById('arena-phase-badge');
    const receipts = document.querySelectorAll('#arena-receipts-list .arena-receipt-row');
    return arena && !arena.hidden && badge && receipts.length >= 1;
  }, null, { timeout: 30000 });
  console.log('VERIFIED: Arena reconnected after reload without restarting test (browser behavior validated).');

  // 3. Demonstrate Mid-Test Cancellation UI
  console.log('DEMONSTRATING: Mid-test cancellation UI…');
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled, null, { timeout: 30000 });
  await page.evaluate(() => focusSection('lab-controls'));
  await page.locator('#lab-start').click();
  await page.waitForFunction(() => !document.getElementById('lab-cancel').disabled, null, { timeout: 30000 });
  await page.locator('#lab-cancel').click();
  await page.waitForFunction(() => {
    const badge = document.getElementById('arena-phase-badge');
    const banner = document.getElementById('arena-summary-banner');
    return (badge && badge.textContent.includes('CANCEL')) || (banner && !banner.hidden);
  }, null, { timeout: 30000 });

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.locator('#arena').scrollIntoViewIfNeeded();
  await page.locator('#arena').screenshot({ path: 'work/arena-cancelled-desktop.png' });
  console.log('CAPTURED: work/arena-cancelled-desktop.png (simulated cancellation UI)');

  // 4. Run trial to completion to demonstrate readable result replay
  console.log('DEMONSTRATING: Trial completion and readable result replay…');
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled, null, { timeout: 30000 });
  await page.evaluate(() => focusSection('lab-controls'));
  await page.locator('#lab-start').click();

  await page.waitForFunction(() => {
    const status = document.getElementById('lab-status');
    return status && status.textContent.startsWith('Baseline saved');
  }, null, { timeout: 120000 });

  // Verify result replay rendered
  await page.waitForFunction(() => {
    const replayBox = document.getElementById('receipt-replay');
    const items = document.querySelectorAll('#receipt-replay-list .replay-item');
    return replayBox && !replayBox.hidden && items.length > 0;
  }, null, { timeout: 30000 });

  await page.locator('#command-center').screenshot({ path: 'work/replay-cards-desktop.png' });
  console.log('CAPTURED: work/replay-cards-desktop.png');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#receipt-replay').screenshot({ path: 'work/replay-cards-phone-390.png' });
  console.log('CAPTURED: work/replay-cards-phone-390.png');

  console.log('[SIMULATED MODEL FIXTURE] Browser streaming, UI reconnect, cancellation, and replay verified. Real-model check remains explicitly pending.');
} finally {
  if (browser) await browser.close();
  server.stdin.end();
  server.kill();
}
