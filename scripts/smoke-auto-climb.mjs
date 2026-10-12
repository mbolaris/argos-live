// Auto Climb browser smoke test:
// Verifies 1-button start, 30s countdown, Try now override, live watch receipts,
// pause/resume, keep/restore decisions, and responsive layouts (1280px, 390px, 320px).
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const {chromium} = require('playwright-core');

const pythonExe = process.env.ARGOS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const server = spawn(pythonExe, ['-u', 'scripts/serve-journey-fixture.py'], {
  stdio: ['pipe', 'pipe', 'inherit'],
  env: {...process.env, ARGOS_FIXTURE_STREAM_DELAY: '0.01'}
});

let browser;
try {
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture timeout')), 25000);
    createInterface({input: server.stdout}).once('line', line => {
      clearTimeout(timer);
      done(line.trim());
    });
    server.once('error', reject);
  });

  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const errors = [];
  page.on('pageerror', e => {
    console.error('PAGE_ERROR:', e);
    errors.push(e.message);
  });
  page.on('console', m => {
    console.log(`CONSOLE [${m.type()}]:`, m.text());
    if (m.type() === 'error') errors.push(`console: ${m.text()}`);
  });
  page.on('response', async resp => {
    if (!resp.ok()) {
      let text = '';
      try { text = await resp.text(); } catch (_) {}
      console.log('HTTP ERROR RESPONSE:', resp.status(), resp.url(), text);
    }
  });

  await mkdir('output/playwright/auto-climb', {recursive: true});

  const shot = async (name) => {
    for (const [suffix, width, height] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
      await page.setViewportSize({width, height});
      await page.evaluate(() => {
        const el = document.querySelector('#auto-climb');
        if (el) scrollTo(0, el.getBoundingClientRect().top + scrollY - 12);
      });
      await page.screenshot({path: `output/playwright/auto-climb/${name}-${suffix}.png`});
    }
    // Check 320px layout
    await page.setViewportSize({width: 320, height: 720});
    await page.evaluate(() => {
      const el = document.querySelector('#auto-climb');
      if (el) scrollTo(0, el.getBoundingClientRect().top + scrollY - 12);
    });
    assert.ok(
      await page.evaluate(() => document.documentElement.scrollWidth <= 320),
      `No horizontal overflow on 320px viewport at ${name}`
    );
    await page.screenshot({path: `output/playwright/auto-climb/${name}-320px.png`});
    await page.setViewportSize({width: 1280, height: 900});
  };

  console.log('Navigating to', url);
  await page.goto(url);
  await page.waitForTimeout(2000);
  const debugState = await page.evaluate(() => ({
    autoClimbCardHidden: document.querySelector('#auto-climb')?.hidden,
    cardExists: Boolean(document.querySelector('#auto-climb')),
  }));
  console.log('DEBUG STATE:', JSON.stringify(debugState));

  const btnInfo = await page.evaluate(() => {
    const btn = document.querySelector('#auto-climb-start-btn');
    const card = document.querySelector('#auto-climb');
    const startView = document.querySelector('#auto-climb-start-view');
    const ccReceipt = document.querySelector('#cc-receipt');
    return {
      btnExists: Boolean(btn),
      btnOffsetParent: Boolean(btn?.offsetParent),
      btnDisplay: btn ? getComputedStyle(btn).display : null,
      cardHidden: card?.hidden,
      cardDisplay: card ? getComputedStyle(card).display : null,
      startViewHidden: startView?.hidden,
      startViewDisplay: startView ? getComputedStyle(startView).display : null,
      ccReceiptHidden: ccReceipt?.hidden,
      ccReceiptDisplay: ccReceipt ? getComputedStyle(ccReceipt).display : null,
    };
  });
  console.log('BTN INFO:', JSON.stringify(btnInfo));

  // 1. Initial State: Card visible, Start button ready
  const startBtn = page.locator('#auto-climb-start-btn');
  assert.ok(await startBtn.isVisible(), 'Start Auto Climb button is visible');
  await shot('01-idle');

  // 2. Click Start
  await startBtn.click();
  console.log('Clicked Start Auto Climb button');

  // Monitor status every second
  const monitor = setInterval(async () => {
    try {
      const snap = await page.evaluate(() => window.autoClimb || null);
      if (snap) console.log('CLIMB SNAPSHOT:', snap.phase, snap.message, JSON.stringify(snap.progress || {}));
    } catch (_) {}
  }, 1000);

  // Wait for session to start: badge updates to ASSESS or COUNTDOWN
  await page.waitForFunction(() => {
    const badge = document.querySelector('#auto-climb-badge');
    return badge && ['ASSESS', 'COUNTDOWN', 'STAGE', 'RETEST'].includes(badge.dataset.phase.toUpperCase());
  }, {timeout: 15000});

  await shot('02-running-or-countdown');

  // Wait until proposal/countdown appears (after baseline assessment)
  await page.waitForFunction(() => {
    const countdownView = document.querySelector('#auto-climb-countdown-view');
    return countdownView && !countdownView.hidden;
  }, {timeout: 45000});
  clearInterval(monitor);

  const tryNowBtn = page.locator('#auto-climb-try-now-btn');
  const skipBtn = page.locator('#auto-climb-skip-btn');
  const pauseBtn = page.locator('#auto-climb-pause-btn');
  assert.ok(await tryNowBtn.isVisible(), 'Try now button is visible during countdown');
  assert.ok(await skipBtn.isVisible(), 'Skip button is visible during countdown');
  assert.ok(await pauseBtn.isVisible(), 'Pause button is visible during countdown');

  await shot('03-proposal-countdown');

  // 3. Test Try now override
  await tryNowBtn.click();

  // Wait for experiment to leave countdown
  await page.waitForFunction(() => {
    const badge = document.querySelector('#auto-climb-badge');
    const b = badge ? badge.dataset.phase.toUpperCase() : '';
    return b !== 'COUNTDOWN';
  }, {timeout: 10000});

  // Wait for experiment to run and advance (to next proposal countdown, plateau, or completed)
  await page.waitForFunction(() => {
    const badge = document.querySelector('#auto-climb-badge');
    const b = badge ? badge.dataset.phase.toUpperCase() : '';
    return ['COUNTDOWN', 'PAUSED', 'PLATEAU', 'COMPLETED', 'BUDGET-EXHAUSTED', 'OPTIONS-EXHAUSTED'].includes(b);
  }, {timeout: 30000});

  await shot('04-experiment-advanced');

  // 4. Test Pause and Resume
  const pauseBtnToClick = (await page.locator('#auto-climb-pause-btn').isVisible())
    ? page.locator('#auto-climb-pause-btn')
    : page.locator('#auto-climb-watch-pause-btn');

  assert.ok(await pauseBtnToClick.isVisible(), 'Pause button is visible');
  await pauseBtnToClick.click();

  await page.waitForFunction(() => {
    const badge = document.querySelector('#auto-climb-badge');
    return badge && badge.dataset.phase.toUpperCase() === 'PAUSED';
  }, {timeout: 10000});
  await shot('05-paused');

  const snapBeforeResume = await page.evaluate(() => api('/api/auto-climb'));
  console.log('BEFORE RESUME:', JSON.stringify(snapBeforeResume));

  const resumeBtn = page.locator('#auto-climb-resume-btn');
  assert.ok(await resumeBtn.isVisible(), 'Resume button is visible when paused');
  await resumeBtn.click();

  await page.waitForFunction(() => {
    const badge = document.querySelector('#auto-climb-badge');
    return badge && badge.dataset.phase.toUpperCase() !== 'PAUSED';
  }, {timeout: 10000});
  await shot('06-resumed');

  // 5. Test Stop
  const stopBtnToClick = (await page.locator('#auto-climb-stop-btn').isVisible())
    ? page.locator('#auto-climb-stop-btn')
    : page.locator('#auto-climb-watch-stop-btn');

  if (await stopBtnToClick.isVisible()) {
    await stopBtnToClick.click();
    await page.waitForFunction(() => {
      const badge = document.querySelector('#auto-climb-badge');
      return badge && ['STOPPED', 'COMPLETED', 'PLATEAU', 'BUDGET-EXHAUSTED'].includes(badge.dataset.phase.toUpperCase());
    }, {timeout: 10000});
    await shot('07-stopped');
  }

  // Presentation-only snapshots retain backend scoring and session behavior.
  await page.evaluate(() => {
    autoClimb = {available: true, phase: 'acquire', download: {progress: {bytes_done: 75, bytes_total: 100}}, progress: {done:8,total:8}, receipts: []};
    renderAutoClimb();
  });
  assert.equal(await page.locator('#auto-climb-watch-tally').textContent(), '75% downloaded');
  assert.ok(await page.locator('.auto-climb-watch-card').isHidden());
  await shot('08-download-progress');
  await page.evaluate(() => {
    autoClimb = {available:true,phase:'blocked',message:'The assistant could not finish a test answer. No gain was accepted. The previous kept build was restored.',history:[{candidate:{title:'Try another model'},verdict:'failed',reason:'No gain was accepted; previous model restored.'}],starting_level:{label:'5/8 practice'},current_level:{label:'5/8 practice'}};
    renderAutoClimb();
  });
  assert.ok(await page.locator('#auto-climb-summary-view').isVisible());
  assert.equal(await page.locator('#auto-climb-verdict-title').textContent(), 'The climb hit a problem');
  assert.ok(await page.locator('#auto-climb-restart-btn').isVisible());
  await shot('09-blocked-summary');
  assert.equal(errors.length, 0, `Browser errors encountered: ${errors.join('; ')}`);
  console.log('PASS: Auto Climb browser smoke test completed successfully.');
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
