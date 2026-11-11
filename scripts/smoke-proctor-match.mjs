// Real-browser check of the Proctor match view over scripts/serve-match-fixture.py.
// Real: dashboard routes, the campaign controller, benchmark scoring, the results
// store and the match replay/comparison. Simulated: the assistant, the agent's
// turns and the model. It verifies what the owner can see; it says nothing about Argos.
// Chromium is a CI proxy for Firefox ESR; this is not physical acceptance.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');
const out = process.env.ARGOS_MATCH_OUTPUT || 'work';
await mkdir(out, {recursive: true});
const python = (process.env.ARGOS_PYTHON || 'python3').split(' ');
const server = spawn(python[0], [...python.slice(1), '-u', 'scripts/serve-match-fixture.py', '--port', '0',
  '--suite', 'quick', '--pace', '0.45', '--slow-answer-seconds', '2'], {stdio: ['ignore', 'pipe', 'inherit']});
let browser;
const checks = [];
function check(name, passed, detail = '') {
  checks.push({name, passed: Boolean(passed)});
  if (!passed) throw new Error(`${name}${detail ? `: ${detail}` : ''}`);
}
try {
  const lines = createInterface({input: server.stdout});
  const url = await new Promise((resolveURL, reject) => {
    const deadline = setTimeout(() => reject(new Error('Fixture dashboard startup timed out')), 20000);
    lines.once('line', line => {
      clearTimeout(deadline);
      const found = line.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[A-Za-z0-9_-]+/);
      if (found) resolveURL(found[0]); else reject(new Error('Fixture dashboard did not provide a session link'));
    });
    server.once('error', reject);
  });
  browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1200, height: 1100},
    ...(process.env.ARGOS_MATCH_VIDEO ? {recordVideo: {dir: process.env.ARGOS_MATCH_VIDEO, size: {width: 1200, height: 1100}}} : {})});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(`script error: ${error.message}`));
  const text = id => page.locator(`#${id}`).textContent();
  const shot = async name => {
    await page.locator('#proctor-match-stages').scrollIntoViewIfNeeded();
    await page.locator('#proctor-live-evaluation').screenshot({path: `${out}/${name}.png`});
  };
  const token = new URL(url).searchParams.get('token');
  const apiGet = path => page.evaluate(async ([target, sessionToken]) => {
    const response = await fetch(target, {headers: {'X-Argos-Token': sessionToken}, cache: 'no-store'});
    return {status: response.status, body: await response.text()};
  }, [path, token]);
  const waitIdle = () => page.waitForFunction(() => !document.getElementById('proctor-campaign-start').disabled, null, {timeout: 60000});
  async function start(scenario) {
    await waitIdle();
    if (await page.locator('#proctor-match-controls').isVisible()) await page.locator('#proctor-match-close').click();
    // The owner opens the workbench to type a task; a running campaign reopens it by itself.
    await page.locator('#workbench').evaluate(node => { node.open = true; });
    await page.locator('#proctor-owner-task').fill(`fixture:${scenario} browser check`);
    await page.locator('#proctor-success-criteria').fill('The watch shows what happened.');
    await page.locator('#proctor-campaign-start').click();
    await page.locator('#proctor-live-evaluation').waitFor({state: 'visible', timeout: 20000});
    // The previous round's result stays up until the new campaign reports in.
    await page.locator('#proctor-match-reveal').waitFor({state: 'hidden', timeout: 20000});
  }
  // The score counts up; wait for it to settle before reading it.
  const scoreSettles = expected => page.waitForFunction(value =>
    document.querySelector('.proctor-match-score-value')?.textContent.trim() === value, expected, {timeout: 5000})
    .then(() => true, () => false);
  const stageNow = () => page.locator('#proctor-match-stages li[data-state="current"]').getAttribute('data-stage');

  await page.goto(url);

  // 1. Watch the round: setup, question, clock, progress; then refresh and rejoin.
  await start('round');
  check('setup is shown before the first question', ['setup', 'round'].includes(await stageNow()));
  await page.waitForFunction(() => document.querySelector('#proctor-match-stages li[data-state="current"]')?.dataset.stage === 'round' &&
    document.querySelectorAll('#proctor-match-pips [data-kind="pass"]').length >= 2, null, {timeout: 30000});
  check('the current question is on screen', (await text('proctor-live-question')).trim().length > 10);
  check('the watch is labelled live', (await text('proctor-match-mode')) === 'LIVE');
  check('one pip per question', await page.locator('#proctor-match-pips li').count() === 20);
  const firstClock = await text('proctor-match-clock');
  await page.waitForFunction(before => document.getElementById('proctor-match-clock').textContent !== before, firstClock, {timeout: 5000});
  check('the clock moves between status polls', true);
  await shot('proctor-match-round');
  const before = await page.locator('#proctor-match-run').getAttribute('title');
  await page.reload();
  await page.waitForFunction(() => document.getElementById('proctor-match-run')?.title.includes('evaluation run'), null, {timeout: 15000});
  check('a refresh rejoins the same watch and run', (await page.locator('#proctor-match-run').getAttribute('title')) === before, before);
  check('the workbench reopens after a refresh', await page.locator('#workbench').evaluate(node => node.open));

  // Lost contact is stated plainly, and so is rejoining.
  await page.route('**/api/proctor-campaign', route => route.abort());
  await page.waitForFunction(() => document.getElementById('proctor-match-notice')?.dataset.kind === 'offline', null, {timeout: 10000});
  check('lost contact is shown plainly', (await text('proctor-match-notice')).includes('Lost contact'));
  await page.unroute('**/api/proctor-campaign');
  await page.waitForFunction(() => document.getElementById('proctor-match-notice')?.dataset.kind !== 'offline', null, {timeout: 10000});
  check('the same run is rejoined after contact returns',
    (await page.locator('#proctor-match-run').getAttribute('title')) === before);

  // 2. Score reveal, comparison, kept or rolled back, owner steps.
  await page.locator('#proctor-match-reveal .proctor-match-decision').waitFor({state: 'visible', timeout: 60000});
  check('the score is revealed', await scoreSettles('19 / 20'), await page.locator('.proctor-match-score-value').textContent());
  check('the answer has a short explanation', (await text('proctor-match-reason')).length > 20);
  check('the comparison names the baseline score', (await page.locator('.proctor-match-delta').textContent()).includes('18'));
  check('wins are listed', (await page.locator('.proctor-match-list[data-kind="win"] strong').textContent()).includes('2'));
  check('regressions are listed', (await page.locator('.proctor-match-list[data-kind="regression"] strong').textContent()).includes('1'));
  check('reply times are compared', (await page.locator('.proctor-match-speed').textContent()).includes('Median reply time'));
  check('the rollback is stated', (await page.locator('.proctor-match-decision-title').textContent()).includes('Rolled back'));
  check('saved run IDs are links', await page.locator('.proctor-match-evidence a[href^="#replay="]').count() === 4);
  check('owner steps are counted', (await page.locator('.proctor-match-owner').textContent()).includes('1 dashboard click'));
  check('the stage strip reaches the comparison', await stageNow() === 'compare');
  await waitIdle();
  await shot('proctor-match-score-and-comparison');
  const runId = (await page.locator('.proctor-match-saved a').getAttribute('href')).replace('#replay=', '');

  // Nothing private leaves the server in the match projection.
  const projection = await apiGet(`/api/proctor-match/run/${runId}`);
  check('the match route answers for a saved run', projection.status === 200);
  for (const secret of ['"reference"', '"expected"', '"scorer"', 'session_id', 'fixture-1', '"hardware"', 'AGENTS.md'])
    check(`the projection omits ${secret}`, !projection.body.includes(secret));
  check('an unknown run is refused', (await apiGet('/api/proctor-match/run/' + '0'.repeat(32))).status === 404);
  check('a malformed run ID is refused', (await apiGet('/api/proctor-match/run/..%2Fstate')).status === 404);

  // 3. Replay: revisit, scrub, speed, and return by link.
  await page.locator('.proctor-match-replay-button').click();
  await page.locator('#proctor-match-controls').waitFor({state: 'visible'});
  check('the replay is labelled as a replay', (await text('proctor-match-mode')) === 'REPLAY');
  check('the replay starts at the first question', (await text('proctor-match-position')).startsWith('Question 1 of 20'));
  await page.locator('#proctor-match-speed').selectOption('4');
  await page.waitForFunction(() => document.getElementById('proctor-match-position').textContent.startsWith('Question 3'), null, {timeout: 20000});
  await shot('proctor-match-replay');
  await page.locator('#proctor-match-pips li:nth-child(20) button').click();
  check('a pip jumps to its question', (await text('proctor-match-position')).startsWith('Question 20 of 20'));
  check('the jumped-to verdict is the saved miss', (await text('proctor-live-verdict')).toLowerCase().includes('miss'));
  await page.locator('#proctor-match-result').click();
  await page.locator('#proctor-match-reveal .proctor-match-decision').waitFor({state: 'visible'});
  check('the replay ends on the same result', await scoreSettles('19 / 20'));
  check('the replay link is in the address', page.url().endsWith(`#replay=${runId}`));
  await page.reload();
  await page.locator('#proctor-match-controls').waitFor({state: 'visible', timeout: 15000});
  check('a refresh returns to the same replay', (await page.locator('#proctor-match-run').getAttribute('title')) === `Saved run ${runId}`);
  await page.locator('.proctor-match-evidence, #proctor-match-result').first().waitFor();
  await page.locator('#proctor-match-close').click();
  check('closing the replay clears the link', !page.url().includes('#replay='));

  // 4. A failed round and a cancelled round are shown as such and never compared.
  for (const [scenario, word] of [['fail', 'failed'], ['cancel', 'cancelled']]) {
    await start(scenario);
    await page.locator('#proctor-match-reveal .proctor-match-score').waitFor({state: 'visible', timeout: 60000});
    check(`a ${word} round is named`, (await page.locator('.proctor-match-score .mission-label').textContent()).toLowerCase().includes(word));
    check(`a ${word} round says where it stopped`, (await page.locator('.proctor-match-score-detail').textContent()).includes('Stopped after 4 of 20'));
    check(`a ${word} round is not compared`, await page.locator('.proctor-match-delta').count() === 0);
    check(`a ${word} round raises a notice`, (await page.locator('#proctor-match-notice').getAttribute('data-kind')) === 'failed');
    await waitIdle();
    await shot(`proctor-match-${word}`);
  }

  // 5. A slow answer is flagged while the question and clock stay up.
  await start('stall');
  await page.waitForFunction(() => document.getElementById('proctor-match-notice')?.dataset.kind === 'stall', null, {timeout: 30000});
  check('a slow answer is flagged', (await text('proctor-match-notice')).includes('taking longer than usual'));
  check('the question stays visible during a slow answer', (await text('proctor-live-question')).trim().length > 10);
  await shot('proctor-match-slow-answer');
  await page.locator('#proctor-match-reveal .proctor-match-score').waitFor({state: 'visible', timeout: 60000});

  // 6. Visible-answer snapshots are shown only when the runtime sends them.
  await start('stream');
  await page.waitForFunction(() => document.getElementById('proctor-live-status')?.textContent.includes('arriving'), null, {timeout: 30000});
  check('partial visible answers appear when the runtime streams', (await text('proctor-live-answer')).trim().length > 0);
  await page.locator('#proctor-match-reveal .proctor-match-score').waitFor({state: 'visible', timeout: 60000});

  // 7. A campaign that stops without a round is recorded and can be reopened.
  await start('crash');
  await page.waitForFunction(() => document.getElementById('proctor-match-notice')?.textContent.includes('campaign-timeout'), null, {timeout: 30000});
  check('a stopped campaign shows its bounded failure code', true);
  await waitIdle();
  await shot('proctor-match-campaign-stopped');
  await page.waitForFunction(() => [...document.querySelectorAll('#proctor-match-picker option')].some(option =>
    option.value.startsWith('campaign:') && option.textContent.includes('campaign-timeout')), null, {timeout: 30000});
  const stopped = await page.locator('#proctor-match-picker option').evaluateAll(options =>
    options.find(option => option.value.startsWith('campaign:') && option.textContent.includes('campaign-timeout')).value);
  await page.locator('#proctor-match-picker').selectOption(stopped);
  await page.locator('#proctor-match-open').click();
  await page.waitForFunction(() => document.getElementById('proctor-match-notice')?.textContent.includes('without a saved round'), null, {timeout: 10000});
  check('a stopped campaign can be reopened from the picker', true);
  const rounds = await page.locator('#proctor-match-picker option').evaluateAll(options =>
    options.filter(option => option.value.startsWith('run:')).length);
  check('saved rounds are listed for replay', rounds >= 7, String(rounds));

  check('no browser script errors', errors.length === 0, errors.join('; '));
  await context.close();
  console.log(JSON.stringify({status: 'passed', checks: checks.length, run_id: runId, screenshots: out}));
} catch (error) {
  console.error(JSON.stringify({status: 'failed', passed: checks.filter(item => item.passed).length,
    failed_check: checks.find(item => !item.passed)?.name || null, error: String(error.message || error).slice(0, 600)}));
  process.exitCode = 1;
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
}
