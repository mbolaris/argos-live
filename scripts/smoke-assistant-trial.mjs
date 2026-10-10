// U10 acceptance in the browser: approval, before/after through a fixture assistant, Keep, Restore,
// plus the diagnostic-only "review" recommendation. Fixture replies only; never real-model evidence.
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
  await page.route('**/style.css?*', async route => {
    const response = await route.fetch();
    await route.fulfill({response, body: await response.text() + '\n.simulation-banner{position:fixed;bottom:0;left:0;right:0;z-index:10000;background:#453329;color:#ffe2b0;text-align:center;font:11px system-ui;padding:5px}'});
  });
  await mkdir('output/playwright/assistant-trial', {recursive: true});
  const shot = async name => {
    await page.evaluate(() => {
      if (!document.querySelector('.simulation-banner')) {
        const banner = document.createElement('div'); banner.className = 'simulation-banner';
        banner.textContent = 'SIMULATED PREVIEW · FIXTURE ASSISTANT REPLIES · NOT A REAL MODEL';
        document.body.prepend(banner);
      }
      // A native modal is above the body watermark in the top layer.
      const modal = document.querySelector('dialog[open] .modal-header');
      if (modal) {
        const badge = document.createElement('span'); badge.className = 'state-badge fixture-modal-label';
        badge.textContent = 'SIMULATED'; modal.prepend(badge);
      }
    });
    for (const [suffix, width, height] of [['desktop', 1280, 900], ['phone', 390, 844]]) {
      await page.setViewportSize({width, height});
      await page.evaluate(() => { const el = document.getElementById('assistant-trial'); scrollTo(0, el.getBoundingClientRect().top + scrollY - 12); });
      await page.screenshot({path: `output/playwright/assistant-trial/${name}-${suffix}.png`});
    }
    await page.setViewportSize({width: 1280, height: 900});
    await page.locator('.fixture-modal-label').evaluateAll(nodes => nodes.forEach(node => node.remove()));
  };
  const status = () => page.evaluate(() => api('/api/assistant-trial'));
  await page.goto(url);
  await page.locator('#cc-next-go').waitFor({state: 'visible'});
  await page.locator('#cc-next-go').click();
  await page.waitForFunction(() => !document.getElementById('cc-receipt').hidden && document.getElementById('command-center').dataset.watching === 'false', null, {timeout: 60000});
  await page.locator('#assistant-trial').waitFor({state: 'visible', timeout: 10000});
  assert.equal((await status()).status, 'none');
  assert.match(await page.locator('#assistant-trial-text').textContent(), /^Lab results don’t change your assistant/);
  await shot('1-offer');

  // ---- Approval: reviewing and "Not now" change nothing.
  await page.locator('#assistant-trial-review').click();
  await page.locator('#assistant-trial-modal').waitFor({state: 'visible'});
  assert.match(await page.locator('#assistant-trial-instruction').textContent(), /^## Answering from text you were given/);
  assert.equal(await page.locator('#assistant-trial-tasks li').count(), 8);
  assert.equal(await page.locator('#assistant-trial-modal .recipe-protection-notice').evaluate(el => el.open), false);
  await shot('2-approval');
  await page.locator('#assistant-trial-close').click();
  assert.equal((await status()).status, 'none', 'Not now changes nothing');

  // ---- Approved trial: before, staged restart, after, result.
  await page.locator('#assistant-trial-review').click();
  await page.locator('#assistant-trial-approve').click();
  await page.waitForFunction(() => /Asking your assistant the trial questions/.test(document.getElementById('assistant-trial-progress').textContent), null, {timeout: 10000});
  await shot('3-running');
  await page.waitForFunction(async () => (await api('/api/assistant-trial')).status === 'on-trial', null, {timeout: 60000, polling: 500});
  await page.waitForFunction(() => !document.getElementById('assistant-trial-result').hidden);
  const result = (await status()).result;
  assert.deepEqual(result.totals, {answer: {before: 0, after: 3, total: 3}, not_stated: {before: 0, after: 3, total: 3},
                                   control: {before: 2, after: 2, total: 2}});
  assert.equal(result.evidence, 'everyday-assistant');
  const card = await page.locator('#assistant-trial').textContent();
  assert.match(card, /Everyday-assistant results · gains: 6 · regressions: 0/);
  assert.match(card, /not meaningful/);
  assert.doesNotMatch(card, /\d+ of 24/, 'No lab score inside assistant evidence');
  assert.equal(await page.locator('#assistant-trial-keep').isVisible(), true);
  await page.locator('#assistant-trial-result details > summary').click();
  await page.evaluate(() => refreshAssistantTrial());
  assert.equal(await page.locator('#assistant-trial-result details').evaluate(el => el.open), true,
    'Polling preserves opened per-question evidence');
  await page.locator('#assistant-trial-result details > summary').click();
  await shot('4-result');

  // ---- Keep, verified; then Restore, verified byte-exact by the controller.
  await page.locator('#assistant-trial-keep').click();
  await page.waitForFunction(async () => (await api('/api/assistant-trial')).status === 'kept', null, {polling: 300});
  assert.match(await page.locator('#assistant-trial-note').textContent(), /Kept and verified/);
  await shot('5-kept');
  await page.locator('#assistant-trial-restore').click();
  await page.waitForFunction(async () => { const v = await api('/api/assistant-trial'); return v.status === 'none' && v.phase === 'restored'; },
    null, {timeout: 20000, polling: 300});
  await page.waitForFunction(() => /Restored and verified: AGENTS.md is byte-for-byte the original/.test(document.getElementById('assistant-trial-note').textContent));
  await shot('6-restored');

  // Cancellation must recover without leaving the approved instruction applied.
  await page.locator('#assistant-trial-review').click();
  await page.locator('#assistant-trial-approve').click();
  await page.locator('#assistant-trial-cancel').waitFor({state: 'visible'});
  await page.locator('#assistant-trial-cancel').click();
  await page.waitForFunction(async () => { const v = await api('/api/assistant-trial'); return !v.active && v.status === 'none' && v.phase === 'cancelled'; },
    null, {timeout: 20000, polling: 300});

  // ---- Diagnostic-only misses recommend reviewing them, not a larger model.
  const proposal = await page.evaluate(() => nextExperiment({suite: 'documents-short', recipe: {preset: 'standard'}, total: 24, correct: 20,
    format_errors: 0, wrong_answers: 4, diagnoses: {wording: 2, requirement: 2}}));
  assert.equal(proposal.kind, 'review');
  assert.match(proposal.why, /^Diagnostic, not a score: every miss kept an accepted answer/);
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
  console.log('PASS: U10 approval, before/after through fixture assistant, keep and restore verified, review recommendation for diagnostic misses; fixture only.');
} finally { if (browser) await browser.close(); server.stdin.end(); server.kill(); }
