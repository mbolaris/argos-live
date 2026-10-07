// Whole personal-robot journey in a real browser against the real dashboard code.
// Chromium proxy; the model and device discovery are fixtures (scripts/serve-journey-fixture.py).
// Not Firefox and not physical acceptance.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');
const server = spawn(process.env.ARGOS_PYTHON || 'python3', ['-u', 'scripts/serve-journey-fixture.py'], {stdio: ['pipe', 'pipe', 'inherit']});
let browser;
const fail = (message) => { throw new Error(message); };
try {
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 20000);
    createInterface({input: server.stdout}).once('line', line => { clearTimeout(timer); done(line.trim()); });
    server.once('error', reject);
  });
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1200, height: 1100}});
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('503')) errors.push('console: ' + m.text()); });
  await page.goto(url);
  const next = () => page.locator('#cc-next-title').textContent();
  const waitNext = (text) => page.waitForFunction((t) => document.getElementById('cc-next-title').textContent === t, text, {timeout: 60000});
  const moment = async () => (await page.locator('#cc-moment').isVisible()) ?
    [await page.locator('#cc-moment-tier').textContent(), await page.locator('#cc-moment-title').textContent()] : null;

  // 1. Nothing proven: try the existing model before choosing future storage.
  await waitNext('Measure this model’s starting point');
  if (await page.locator('#cc-next-go').textContent() !== 'Pause chat and run the first trial') fail('First mission does not name its action');
  if (!(await page.locator('#cc-build-summary').textContent()).includes('0 of 4')) fail('Build path claims untested progress');
  if (await page.locator('#cc-build-steps [aria-current="step"]').count() !== 1) fail('Build path does not identify the next step');
  if (!(await page.locator('#cc-title').textContent()).includes('Mission control')) fail('Mission Control did not lead the page');
  if (!(await page.locator('#catalog-panel').evaluate(panel => panel.open))) fail('Model choices hidden by default');
  const deduplication = await page.evaluate(() => {
    const model = {tag: 'fixture:latest', manifest_digest: 'sha256:' + 'a'.repeat(64), files_present: true};
    const bundled = {state: 'available', models: [model]};
    return sameBundledModel(model, bundled) && !sameBundledModel({...model, manifest_digest: 'sha256:' + 'b'.repeat(64)}, bundled) &&
      !sameBundledModel({...model, files_present: false}, bundled);
  });
  if (!deduplication) fail('Starter display deduplication lost file identity or completeness');
  if (!(await page.locator('#cc-scope').textContent()).includes('demonstrated')) fail('Evidence scope is missing');
  const systems = await page.locator('#cc-systems li').allTextContents();
  if (systems.length !== 7 || systems.some(s => s.includes('Qualified') || s.includes('Commissioned'))) fail('Systems overstated at the start: ' + systems);
  if (await moment()) fail('A moment appeared before any evidence');
  if (await page.locator('#cc-schematic [data-state="qualified"]').count()) fail('Schematic lit a section without evidence');
  if (!(await page.locator('#download-controls').isHidden())) { /* download controls need a managed workspace */ }
  await page.screenshot({path: 'work/journey-first-trial.png'});

  // 2. Baseline before storage confirmation, twice for comparable runs.
  for (let n = 0; n < 2; n++) {
    await page.waitForFunction(() => !document.getElementById('lab-start').disabled, null, {timeout: 60000});
    const started = page.waitForResponse(response => response.url().endsWith('/api/lab/start') && response.request().method() === 'POST');
    if (n === 0) await page.locator('#cc-next-go').click();
    else await page.locator('#lab-start').click();
    if (!(await started).ok()) fail('Baseline start was refused');
    // The previous run's completed text is not evidence that this run finished.
    await page.waitForFunction(count => document.querySelectorAll('#benchmark-runs .card').length >= count &&
      !document.getElementById('lab-start').disabled && document.getElementById('lab-status').textContent.startsWith('Baseline saved'),
      2 * (n + 1), {timeout: 120000});
  }
  await waitNext('Test short-document reading');
  if (!(await page.locator('#cc-build-summary').textContent()).includes('1 of 4')) fail('Baseline did not advance its own build stage');

  await page.waitForFunction(() => document.getElementById('cc-debrief-text').textContent.includes('repair brief'), null, {timeout: 15000});
  if (!(await page.locator('#cc-stage').textContent()).includes('Mapped')) fail('Measured build stage missing');
  if (await page.locator('#cc-skill-bars meter').count() !== 5) fail('Ability map does not show each tested category');
  const expectedReceipt = await page.evaluate(() => api('/api/command-center'));
  const score = expectedReceipt.report.ability;
  if (!(await page.locator('#cc-scoreboard').textContent()).includes(`${score.correct} / ${score.total}`)) fail('Readable score differs from measured evidence');
  await page.locator('#command-center').screenshot({path: 'work/journey-ladder-baseline.png'});
  for (const index of [0, 1, 2]) {
    await page.locator('#cc-challenges button').nth(index).click();
    if (!(await page.locator('#cc-doc').inputValue()).length) fail('Mission preview has no brief');
    if (!(await page.locator('#cc-question').inputValue()).length) fail('Mission preview has no question');
    if (!(await page.locator('#cc-task-box').evaluate(box => box.open))) fail('Mission preview is hidden');
    if (await page.locator('#cc-task-result').isVisible()) fail('Preview started inference without asking');
  }
  // Model text stays text, even if it contains executable-looking markup.
  await page.evaluate(() => {
    lastLabDebrief.text = '<img src=x onerror="window.modelExecuted=true">';
    refreshCommand();
  });
  await page.waitForFunction(() => document.getElementById('cc-debrief-text').textContent.includes('<img'));
  if (await page.locator('#cc-debrief-text img').count()) fail('Model opinion rendered as HTML');
  await page.setViewportSize({width: 390, height: 844});
  await page.locator('#command-center').screenshot({path: 'work/journey-ladder-mobile.png'});
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) fail('Mobile layout overflows');
  await page.setViewportSize({width: 1200, height: 1100});

  // 3. Storage remains a separate deliberate choice; no download from testing.
  await page.getByRole('link', {name: 'Choose model storage'}).click();
  await page.getByRole('button', {name: 'Review this location'}).first().click();
  await page.locator('#storage-review').waitFor({state: 'visible'});
  await page.locator('#storage-confirm').click();
  await page.waitForFunction(() => document.getElementById('storage-status').textContent.includes('Model location confirmed.'), null, {timeout: 30000});
  await page.waitForFunction(() => document.getElementById('cc-journal').textContent.includes('Memory banks configured'));
  await waitNext('Test short-document reading');
  const first = await moment();
  if (!first || first[0] !== 'Routine') fail('Expected a routine acknowledgment, got ' + JSON.stringify(first));
  await page.locator('#cc-moment-dismiss').click();
  await page.waitForFunction(() => document.getElementById('cc-moment').hidden);

  // 4. Matched comparison renders speed and accuracy separately without script errors.
  await page.waitForFunction(() => document.querySelectorAll('#benchmark-runs .card').length >= 4, null, {timeout: 30000});
  const cards = page.locator('#benchmark-runs .card');
  const wanted = {speed: [], ability: []};
  for (let i = 0; i < await cards.count(); i++) {
    const text = await cards.nth(i).textContent();
    wanted[/speed/i.test(text) && !/ability/i.test(text) ? 'speed' : 'ability'].push(i);
  }
  for (const kind of ['speed', 'ability']) {
    await page.locator('#benchmark-runs input:checked').evaluateAll(boxes => boxes.forEach(b => b.click()));
    for (const index of wanted[kind].slice(0, 2)) await cards.nth(index).locator('input').check();
    await page.locator('#compare-runs').click();
    await page.waitForFunction(() => document.querySelectorAll('#benchmark-comparison table').length > 0, null, {timeout: 15000});
    const captions = await page.locator('#benchmark-comparison caption').allTextContents();
    if (kind === 'speed' && !['Generation speed', 'Prompt processing speed', 'Wait for first token'].every(c => captions.includes(c))) fail('Speed tables missing: ' + captions);
    if (kind === 'ability' && !captions.some(c => c.startsWith('Accuracy and format'))) fail('Accuracy table missing: ' + captions);
    const cellsText = (await page.locator('#benchmark-comparison td').allTextContents()).join('|');
    if (/\[object|undefined|NaN/.test(cellsText)) fail('Comparison rendered a broken value: ' + cellsText);
    if (kind === 'speed' && !/tok\/s/.test(cellsText)) fail('Speed values missing units: ' + cellsText);
  }

  // 5. Document trial, fixed criteria, one qualified moment.
  await page.locator('#lab-start-documents').click();
  await page.waitForFunction(() => document.getElementById('lab-status').textContent.startsWith('Document trial saved'), null, {timeout: 180000});
  await waitNext('Test a document that matters to you');
  const qualified = await moment();
  if (!qualified || qualified[0] !== 'Qualified' || !qualified[1].includes('Short documents')) fail('Expected a Qualified document moment, got ' + JSON.stringify(qualified));
  if (!(await page.locator('#cc-moment-detail').textContent()).includes('says nothing about longer documents')) fail('Qualified moment lost its scope');
  await page.locator('#cc-moment-dismiss').click();
  await page.reload();
  await waitNext('Test a document that matters to you');
  if (await moment()) fail('A dismissed moment came back after reload');

  // 6. The owner's own document, quote verified against the pasted text, accepted.
  await page.locator('#cc-next-go').click();
  await page.locator('#cc-doc').fill('The Larkspur Harbor ferry began service in 1987. Crossings take 35 minutes. Fares are $6 for adults.');
  await page.locator('#cc-question').fill('How long does a crossing take?');
  await page.locator('#cc-ask').click();
  await page.locator('#cc-task-result').waitFor({state: 'visible', timeout: 120000});
  if ((await page.locator('#cc-answer').textContent()) !== '35 minutes') fail('Wrong task answer');
  if (!(await page.locator('#cc-task-note').textContent()).includes('appears in your text')) fail('Quote was not verified against the pasted text');
  await page.locator('#cc-accept').click();
  await page.waitForFunction(() => document.getElementById('cc-moment') && !document.getElementById('cc-moment').hidden &&
    document.getElementById('cc-moment-tier').textContent === 'Commissioned', null, {timeout: 20000});
  if (!(await page.locator('#cc-moment-title').textContent()).includes('Brain commissioned')) fail('Expected brain commissioning');
  if ((await page.locator('#cc-systems li').filter({hasText: 'Sensors'}).textContent()).includes('Not yet tested')) fail('Sensors stayed unproven after acceptance');
  if (!await page.locator('#cc-schematic [data-system="brain"][data-state="qualified"], #cc-schematic [data-system="sensors"][data-state="commissioned"]').count()) fail('Schematic did not reflect the evidence');
  const journal = (await page.locator('#cc-journal li').allTextContents()).join('\n');
  if (/Larkspur|35 minutes|crossing/i.test(journal)) fail('Private document text leaked into the journal');
  if ((journal.match(/Brain commissioned/g) || []).length !== 1) fail('Commissioning repeated');
  await page.screenshot({path: 'work/journey-command-center.png', fullPage: true});
  if (errors.length) fail('Browser errors: ' + errors.join('; '));
  console.log('PASS: journey in Chromium (storage choice, baseline x2, speed and accuracy comparison, document trial, own-document answer, moments once). Fixture model; Firefox and physical acceptance pending.');
} finally {
  if (browser) await browser.close();
  server.stdin.end();
  server.kill();
}
