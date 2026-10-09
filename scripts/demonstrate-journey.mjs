// Demonstrate the complete Start -> Watch -> Change -> Retest -> Compare -> Restore journey.
// Captures actual browser screenshots against the real dashboard server and controllers,
// asserts outcomes and response schemas, and clearly labels all screenshots as simulated fixtures.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');
const server = spawn(process.env.ARGOS_PYTHON || 'python3', ['-u', 'scripts/serve-journey-fixture.py'], {stdio: ['pipe', 'pipe', 'inherit']});
let browser;

function fail(msg) {
  throw new Error(msg);
}

try {
  let rl;
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 20000);
    rl = createInterface({input: server.stdout});
    rl.once('line', line => { clearTimeout(timer); rl.close(); done(line.trim()); });
    server.once('error', reject);
  });
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1200, height: 1100}});

  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('503')) errors.push('console: ' + m.text()); });

  await page.goto(url);

  // Helper to attach prominent, unmissable fixture label across all screenshots
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

  // 1. START: Initial Mission Control state
  await page.waitForFunction(() => document.getElementById('cc-title') && document.getElementById('cc-next-go'));
  await page.waitForFunction(() => !document.getElementById('catalog-panel').open);
  await page.waitForFunction(() => document.querySelectorAll('#model-curated .card').length > 0);
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled, null, {timeout: 60000});

  // Verify collapsed legacy inventory and single recommended candidate
  const legacyOpen = await page.locator('#catalog-panel').evaluate(el => el.open);
  if (legacyOpen) fail('Legacy catalog should be collapsed by default');
  const curatedText = await page.locator('#model-curated').textContent();
  if (!curatedText.includes('Recommended upgrade')) fail('Curated shortlist does not display recommended upgrade badge');
  if (curatedText.includes('higher accuracy')) fail('Curated shortlist makes unsupported accuracy promise before testing');

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-1-start.png'});
  console.log('PASS [Step 1: Start]: Captured work/journey-1-start.png (labeled fixture)');

  // 2. WATCH: Trigger first baseline (standard recipe) and watch live arena
  const started1 = page.waitForResponse(r => r.url().endsWith('/api/lab/start') && r.request().method() === 'POST');
  await page.locator('#lab-start').click();
  const resp1 = await started1;
  if (!resp1.ok()) fail('Baseline 1 start failed');

  await page.waitForFunction(() => document.getElementById('arena') && !document.getElementById('arena').hidden);
  await page.waitForFunction(() => {
    const prompt = document.getElementById('arena-current-prompt');
    const badge = document.getElementById('arena-phase-badge');
    const stream = document.getElementById('arena-current-stream');
    return (prompt && prompt.textContent.length > 0) || (badge && badge.textContent !== 'Idle') || (stream && stream.textContent.length > 0);
  });

  // Assert live watch indicators
  const arenaVisible = await page.locator('#arena').isVisible();
  if (!arenaVisible) fail('Arena not visible during live run');
  const stopVisible = await page.locator('#lab-cancel').isVisible();
  if (!stopVisible) fail('Stop button not visible during live run');

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-2-watch.png'});
  console.log('PASS [Step 2: Watch]: Captured work/journey-2-watch.png (labeled fixture)');

  // Wait for Baseline 1 to complete
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length >= 2 &&
    !document.getElementById('lab-start').disabled &&
    document.getElementById('lab-status').textContent.startsWith('Baseline saved'), null, {timeout: 120000});

  // 3. CHANGE: Open recipe experiment modal, preview concise preset, assert personality protection, select concise
  await page.locator('#receipt-change').click();
  await page.waitForFunction(() => document.getElementById('recipe-modal').open);

  const modalText = await page.locator('#recipe-modal').textContent();
  if (!modalText.includes('This experiment modifies the Lab test recipe only')) {
    fail('Recipe modal lacks OpenClaw assistant protection notice');
  }
  if (!modalText.includes('Follow the requested output format; omit extra prose.')) {
    fail('Concise preset instruction preview missing');
  }

  await attachFixtureBanner();
  await page.screenshot({path: 'work/journey-3-change.png'});
  console.log('PASS [Step 3: Change]: Captured work/journey-3-change.png (labeled fixture)');

  await page.locator('#recipe-select-only').click();
  await page.waitForFunction(() => !document.getElementById('recipe-modal').open);
  await page.waitForFunction(() => document.getElementById('lab-active-recipe').textContent.includes('Strict format instructions (concise)'));

  // 4. RETEST: Run second baseline with the changed recipe
  await page.waitForFunction(() => !document.getElementById('lab-start').disabled, null, {timeout: 60000});
  const started2 = page.waitForResponse(r => r.url().endsWith('/api/lab/start') && r.request().method() === 'POST');
  await page.locator('#lab-start').click();
  const resp2 = await started2;
  if (!resp2.ok()) fail('Baseline 2 (retest) start failed');

  // Wait for Baseline 2 (concise recipe) to complete
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length >= 4 &&
    !document.getElementById('lab-start').disabled &&
    document.getElementById('lab-status').textContent.startsWith('Baseline saved'), null, {timeout: 120000});

  // 5. COMPARE: Execute controlled experiment comparison between Standard and Concise runs
  // Uncheck any selected checkboxes first
  await page.locator('#benchmark-runs input:checked').evaluateAll(boxes => boxes.forEach(b => b.click()));

  // Identify the two ability runs using authenticated API calls to inspect full runs with recipes
  const {standardId, conciseId} = await page.evaluate(async () => {
    const listing = await api('/api/benchmarks');
    const abilitySummaries = listing.runs.filter(r => r.kind === 'ability');
    let std = null, con = null;
    for (const item of abilitySummaries) {
      const full = await api('/api/benchmarks/run/' + item.id);
      const preset = full.recipe?.preset || 'standard';
      if (preset === 'standard' && !std) std = item.id;
      if (preset === 'concise' && !con) con = item.id;
    }
    return {standardId: std, conciseId: con};
  });

  if (!standardId || !conciseId) {
    fail(`Could not find both standard and concise ability runs (std=${standardId}, con=${conciseId})`);
  }

  // Check the standard and concise ability runs in UI
  await page.locator(`#benchmark-runs input[value="${standardId}"]`).check();
  await page.locator(`#benchmark-runs input[value="${conciseId}"]`).check();

  // Assert #compare-experiment is enabled
  const expBtnDisabled = await page.locator('#compare-experiment').isDisabled();
  if (expBtnDisabled) fail('Controlled experiment comparison button is disabled for paired runs');

  await page.locator('#compare-experiment').click();
  await page.waitForFunction(() => document.querySelectorAll('#experiment-comparison .experiment-card').length > 0, null, {timeout: 15000});

  // Assert controlled comparison API response schema directly
  const comparisonData = await page.evaluate(async ({std, con}) => {
    return await api(`/api/benchmarks/experiment?baseline=${std}&candidate=${con}`);
  }, {std: standardId, con: conciseId});

  if (comparisonData.schema !== 'argos-experiment/1') fail('Schema mismatch: ' + comparisonData.schema);
  if (comparisonData.intervention !== 'recipe') fail('Intervention mismatch: ' + comparisonData.intervention);
  if (!comparisonData.delta || !comparisonData.delta.verdict) fail('Missing delta verdict in comparison response');
  if (!comparisonData.limitations) fail('Missing honest limitations disclaimer in comparison response');

  // Assert UI rendered content
  const expText = await page.locator('#experiment-comparison').textContent();
  if (!expText.includes('Instruction Recipe Intervention')) {
    fail('Controlled comparison did not render Instruction Recipe Intervention title: ' + expText);
  }
  if (!expText.includes('Observed +1 is not confirmed general improvement without independent validation')) {
    fail('Controlled comparison missing honest limitations disclaimer: ' + expText);
  }

  await attachFixtureBanner();
  await page.locator('#experiment-comparison').scrollIntoViewIfNeeded();
  await page.screenshot({path: 'work/journey-4-compare.png'});
  console.log('PASS [Step 4: Compare]: Captured work/journey-4-compare.png (labeled fixture)');

  // 6. RESTORE: Restore standard recipe and verify active recipe bar updates
  await page.locator('#lab-recipe-restore').click();
  await page.waitForFunction(() => document.getElementById('lab-recipe-restore').hidden ||
    document.getElementById('lab-active-recipe').textContent.includes('Standard calibration'));

  // Verify session recipe restored via authenticated API; restoring standard returns selected: null
  const recipesState = await page.evaluate(async () => {
    return await api('/api/lab/recipes');
  });
  if (recipesState.selected !== null) {
    fail(`Recipe restore failed; expected selected: null, got ${JSON.stringify(recipesState.selected)}`);
  }

  await attachFixtureBanner();
  await page.locator('#lab-controls').scrollIntoViewIfNeeded();
  await page.screenshot({path: 'work/journey-5-restore.png'});
  console.log('PASS [Step 5: Restore]: Captured work/journey-5-restore.png (labeled fixture)');

  if (errors.length) fail('Browser recorded errors: ' + errors.join('; '));
  console.log('ALL 5 JOURNEY DEMONSTRATION STEPS AND ASSERTIONS COMPLETED SUCCESSFULLY');
} catch (err) {
  console.error('Demonstration journey failed:', err);
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
