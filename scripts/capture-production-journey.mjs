// Capture production UI screenshots across the complete 6-stage playable loop:
// 1. Mission (Home screen with AI, model, mission preview, qualification criteria, and curriculum roadmap)
// 2. Streaming (Active test in Arena with streaming tokens, item counter, HUD)
// 3. Debrief (Result debrief, representative replay with failure reasons, action buttons, curriculum bound to evidence)
// 4. Improvement (Improvement recipe modal with concise preview and assistant protection notice)
// 5. Comparison (Matched comparison table, changed answers diff, Keep/Restore recommendation)
// 6. Storage (Storage dialog recommending one eligible disk with factual reason, RAM warning, and guardrails)
// Across both Desktop (1200x900) and Phone (390x844).

import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve, join } from 'node:path';
import { mkdir, copyFile } from 'node:fs/promises';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');

const defaultPython = process.platform === 'win32'
  ? (process.env.ARGOS_PYTHON || 'C:\\Users\\mike\\AppData\\Local\\Python\\bin\\python.exe')
  : 'python3';

const outDir = resolve('work/production-screenshots');
const artifactDir = resolve('C:\\Users\\mike\\.gemini\\antigravity-ide\\brain\\babb493d-1fa1-4c59-b562-adcec2166ece\\screenshots');

await mkdir(outDir, { recursive: true });
await mkdir(artifactDir, { recursive: true });

async function startFixtureServer() {
  const proc = spawn(defaultPython, ['-u', 'scripts/serve-journey-fixture.py'], { stdio: ['pipe', 'pipe', 'inherit'] });
  const url = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 25000);
    const rl = createInterface({ input: proc.stdout });
    rl.once('line', line => { clearTimeout(timer); rl.close(); done(line.trim()); });
    proc.once('error', reject);
  });
  return { proc, url };
}

async function captureViewport(vp, browser) {
  console.log(`\n=============================================================`);
  console.log(`Capturing production flow for ${vp.name.toUpperCase()} (${vp.width}x${vp.height})`);
  console.log(`=============================================================`);

  const { proc: serverProc, url } = await startFixtureServer();
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });

  const attachBanner = async () => {
    await page.evaluate(() => {
      let b = document.getElementById('fixture-watermark-banner');
      if (!b) {
        b = document.createElement('div');
        b.id = 'fixture-watermark-banner';
        b.className = 'fixture-watermark-banner';
        b.textContent = 'SIMULATED FIXTURE RUN · NOT REAL INFERENCE · FIREFOX ESR & TORONADO PHYSICAL GPU PENDING';
        document.body.prepend(b);
      }
    });
  };

  try {
    await page.goto(url);
    await attachBanner();

    // -------------------------------------------------------------
    // Screen 1: First Mission (Home)
    // -------------------------------------------------------------
    console.log(`[${vp.name}] Capturing 1: First Mission...`);
    await page.waitForFunction(() => document.getElementById('cc-title') && document.getElementById('cc-next-go'));
    await page.waitForFunction(() => document.getElementById('cc-next-title')?.textContent === 'Read this brief', null, { timeout: 30000 });
    await page.waitForFunction(() => !document.getElementById('cc-next-go').disabled);
    await attachBanner();
    await page.waitForTimeout(300);

    const shot1 = join(outDir, `prod-1-mission-${vp.name}.png`);
    await page.screenshot({ path: shot1, fullPage: false });
    await copyFile(shot1, join(artifactDir, `prod-1-mission-${vp.name}.png`));
    console.log(`Saved ${shot1}`);

    // -------------------------------------------------------------
    // Screen 2: Active Streaming Test in Arena
    // -------------------------------------------------------------
    console.log(`[${vp.name}] Starting test & Capturing 2: Streaming...`);
    const docStartReq = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
    await page.locator('#cc-next-go').click();
    await docStartReq;

    // Wait for Arena to display actual passage & streaming answer tokens
    await page.waitForFunction(() => {
      const arena = document.getElementById('arena');
      const prompt = document.getElementById('arena-current-prompt');
      const stream = document.getElementById('arena-current-stream');
      return arena && !arena.hidden &&
        prompt && prompt.textContent.includes('PASSAGE') &&
        stream && stream.textContent.length > 5 &&
        stream.textContent !== 'Awaiting model response…' &&
        stream.textContent !== 'Generating response…';
    }, null, { timeout: 30000 });

    await page.evaluate(() => {
      const arena = document.getElementById('arena');
      if (arena) arena.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    await attachBanner();
    await page.waitForTimeout(200);

    const shot2 = join(outDir, `prod-2-streaming-${vp.name}.png`);
    await page.screenshot({ path: shot2, fullPage: false });
    await copyFile(shot2, join(artifactDir, `prod-2-streaming-${vp.name}.png`));
    console.log(`Saved ${shot2}`);

    // -------------------------------------------------------------
    // Screen 3: Result Debrief & Weakness Replay
    // -------------------------------------------------------------
    console.log(`[${vp.name}] Waiting for run completion & Capturing 3: Debrief...`);
    await page.waitForFunction(() => {
      const badge = document.getElementById('arena-phase-badge');
      const status = document.getElementById('lab-status');
      const replayBox = document.getElementById('receipt-replay');
      const baselineSaved = (badge && badge.textContent.includes('COMPLETED')) || (status && status.textContent.includes('Document trial saved'));
      const idRetained = sessionStorage.getItem('argos_baseline_doc_run_id') !== null;
      return baselineSaved && idRetained && replayBox && !replayBox.hidden;
    }, null, { timeout: 90000 });

    // Scroll to #cc-receipt so debrief and replay are framed well
    await page.evaluate(() => {
      const el = document.getElementById('cc-receipt');
      if (el) el.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    await attachBanner();
    await page.waitForTimeout(400);

    const shot3 = join(outDir, `prod-3-debrief-${vp.name}.png`);
    await page.screenshot({ path: shot3, fullPage: false });
    await copyFile(shot3, join(artifactDir, `prod-3-debrief-${vp.name}.png`));
    console.log(`Saved ${shot3}`);

    // -------------------------------------------------------------
    // Screen 4: Improvement Recipe Modal
    // -------------------------------------------------------------
    console.log(`[${vp.name}] Opening recipe modal & Capturing 4: Recipe...`);
    const changeBtn = page.locator('#receipt-change');
    await changeBtn.waitFor({ state: 'visible' });
    await changeBtn.click();

    await page.waitForFunction(() => document.getElementById('recipe-modal')?.open, null, { timeout: 10000 });
    await attachBanner();
    await page.waitForTimeout(300);

    const shot4 = join(outDir, `prod-4-recipe-${vp.name}.png`);
    await page.screenshot({ path: shot4, fullPage: false });
    await copyFile(shot4, join(artifactDir, `prod-4-recipe-${vp.name}.png`));
    console.log(`Saved ${shot4}`);

    // -------------------------------------------------------------
    // Screen 5: Matched Comparison & Keep/Restore
    // -------------------------------------------------------------
    console.log(`[${vp.name}] Running candidate & Capturing 5: Comparison...`);
    const candStartReq = page.waitForResponse(r => r.url().endsWith('/api/lab/start-documents') && r.request().method() === 'POST');
    await page.locator('#recipe-run').click();
    await candStartReq;

    // Wait for recipe modal to close
    await page.waitForFunction(() => !document.getElementById('recipe-modal')?.open);

    // Wait for candidate trial to complete and auto-render controlled comparison
    await page.waitForFunction(() => {
      const card = document.querySelector('#experiment-comparison .experiment-card');
      const rec = document.getElementById('experiment-recommendation');
      return card !== null && rec !== null;
    }, null, { timeout: 90000 });

    // Scroll comparison card into view
    await page.evaluate(() => {
      const el = document.getElementById('experiment-comparison');
      if (el) el.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    await attachBanner();
    await page.waitForTimeout(400);

    const shot5 = join(outDir, `prod-5-compare-${vp.name}.png`);
    await page.screenshot({ path: shot5, fullPage: false });
    await copyFile(shot5, join(artifactDir, `prod-5-compare-${vp.name}.png`));
    console.log(`Saved ${shot5}`);

    // -------------------------------------------------------------
    // Screen 6: Storage Selection Dialog
    // -------------------------------------------------------------
    console.log(`[${vp.name}] Opening storage review modal & Capturing 6: Storage...`);
    await page.evaluate(async () => {
      window.resetStorageForReview();
      const tag = 'qwen2.5:1.5b-instruct-q4_K_M';
      await window.reviewDownload({ tag }, tag);
    });

    await page.waitForFunction(() => document.getElementById('download-review')?.open, null, { timeout: 15000 });
    await attachBanner();
    await page.waitForTimeout(400);

    const shot6 = join(outDir, `prod-6-storage-${vp.name}.png`);
    await page.screenshot({ path: shot6, fullPage: false });
    await copyFile(shot6, join(artifactDir, `prod-6-storage-${vp.name}.png`));
    console.log(`Saved ${shot6}`);

  } finally {
    await page.close();
    serverProc.kill();
  }
}

let browserInstance;
try {
  browserInstance = await chromium.launch({ headless: true });

  const viewports = [
    { name: 'desktop', width: 1200, height: 900 },
    { name: 'phone', width: 390, height: 844 },
  ];

  for (const vp of viewports) {
    await captureViewport(vp, browserInstance);
  }

  console.log('\nAll 12 production screenshots successfully captured and copied to artifact directory!');
} finally {
  if (browserInstance) await browserInstance.close();
}
