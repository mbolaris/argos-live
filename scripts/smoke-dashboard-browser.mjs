// Real browser check using playwright-core already pinned by the runtime lock.
// Chromium is a CI proxy for Firefox ESR; this is not physical ISO acceptance.
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve('work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');
const home = await mkdtemp(join(tmpdir(), 'argos-dashboard-browser-'));
const seed = spawnSync('python3', ['-c',
  "import sys; sys.path[:0]=['runtime','tests']; from test_results import ability_result; from argoslive.results import Store; s=Store(); a=ability_result(); b=ability_result('wrong'); b['model']='<b>Fixture label</b>'; s.save(a); s.save(b)"],
  {env: {...process.env, HOME: home, USERPROFILE: home}, encoding: 'utf8'});
if (seed.status !== 0) throw new Error('Public benchmark browser fixtures failed');
const server = spawn('python3', ['-u', 'web/server.py', '--port', '0'], {
  env: {...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('OPENCLAW_'))),
    HOME: home, USERPROFILE: home, XDG_CONFIG_HOME: join(home, 'config')},
  stdio: ['ignore', 'pipe', 'pipe']
});
let browser;
try {
  const lines = createInterface({input: server.stdout});
  const url = await new Promise((resolveURL, reject) => {
    const deadline = setTimeout(() => reject(new Error('Dashboard startup timed out')), 15000);
    lines.once('line', line => {
      clearTimeout(deadline);
      const match = line.match(/http:\/\/127\.0\.0\.1:\d+\/\?token=[A-Za-z0-9_-]+/);
      if (!match) reject(new Error('Dashboard did not provide a session link'));
      else resolveURL(match[0]);
    });
    server.once('error', reject);
  });
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1200, height: 1000}});
  const errors = [];
  page.on('pageerror', () => errors.push('Browser script error'));
  page.on('console', message => { if (message.type() === 'error') errors.push('Browser console error'); });
  // Public display fixture only; no model weights, configuration or readiness
  // claim. Other endpoints still exercise the actual unconfigured server.
  await page.route('**/api/models', async route => {
    const response = await route.fetch();
    const value = await response.json();
    value.bundled = {state: 'available', read_only: true, models: [{tag: 'qwen3:0.6b'}]};
    value.selected_source = 'bundled';
    await route.fulfill({response, json: value});
  });
  const response = await page.goto(url);
  if (response.status() !== 200) throw new Error('Dashboard page did not load');
  await page.getByText('Live measurements refreshed. Missing measurements remain unknown.', {exact: true}).waitFor({timeout: 60000});
  if (await page.locator('#hardware .card').count() !== 8) throw new Error('Missing live status cards');
  if (await page.locator('#capabilities .card').count() !== 10) throw new Error('Missing capability cards');
  await page.waitForFunction(() => document.querySelectorAll('#model-catalog .card').length >= 8, null, {timeout: 60000});
  await page.getByText('Bundled starter · qwen3:0.6b', {exact: true}).waitFor();
  if (!(await page.locator('#bundled-models').textContent()).includes('Selected for this session.')) {
    throw new Error('Bundled source selection was not displayed');
  }
  await page.locator('summary').click();
  if (!(await page.locator('#chat').isDisabled())) throw new Error('Unconfigured assistant incorrectly enabled chat');
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length === 2);
  if (await page.locator('#benchmark-runs b').count()) throw new Error('Result label was treated as markup');
  for (const input of await page.locator('#benchmark-runs input').all()) await input.check();
  await page.locator('#compare-runs').click();
  await page.getByText('accuracy: 1.000', {exact: true}).waitFor();
  const csvPending = page.waitForEvent('download');
  await page.locator('#download-comparison').click();
  const csvDownload = await csvPending;
  const csv = await readFile(await csvDownload.path(), 'utf8');
  if (!csv.includes('manifest_digest') || !csv.includes('accuracy')) throw new Error('Comparison CSV failed');
  const jsonPending = page.waitForEvent('download');
  await page.locator('#benchmark-runs button').first().click();
  const jsonDownload = await jsonPending;
  if (JSON.parse(await readFile(await jsonDownload.path(), 'utf8')).kind !== 'ability') throw new Error('Result JSON failed');
  await page.unroute('**/api/models');
  await page.locator('#refresh').click();
  await page.locator('#refresh').waitFor({state: 'visible'});
  await page.waitForFunction(() => !document.getElementById('refresh').disabled, null, {timeout: 60000});
  if (await page.locator('#bundled-models .card').count()) throw new Error('Stale bundled source display');
  if (errors.length) throw new Error('Browser script failed');
  await page.screenshot({path: 'work/dashboard-desktop.png', fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  if (!(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))) {
    throw new Error('Dashboard overflows narrow viewport');
  }
  await page.screenshot({path: 'work/dashboard-narrow.png', fullPage: true});
  console.log('PASS: live/capability cards, disabled unconfigured chat, refresh, responsive layout, no script errors. Chromium proxy; Firefox/physical acceptance pending.');
} finally {
  if (browser) await browser.close();
  const stopped = new Promise(resolveStop => server.once('exit', resolveStop));
  server.kill('SIGINT');
  await Promise.race([stopped, new Promise(resolveStop => setTimeout(() => {server.kill('SIGKILL'); resolveStop();}, 3000))]);
  await rm(home, {recursive: true, force: true});
}
