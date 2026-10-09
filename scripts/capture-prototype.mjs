// Capture screenshots of the visual prototype across desktop (1280x900) and mobile phone (390x844)
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { resolve } from 'node:path';
import { mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';

const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const { chromium } = require('playwright-core');

const defaultPython = process.platform === 'win32' 
  ? (process.env.ARGOS_PYTHON || 'C:\\Users\\mike\\AppData\\Local\\Python\\bin\\python.exe') 
  : 'python3';

mkdirSync('work/prototype', { recursive: true });

console.log('Spawning fixture server with', defaultPython);
const server = spawn(defaultPython, ['-u', 'scripts/serve-journey-fixture.py'], {stdio: ['pipe', 'pipe', 'inherit']});
let browser;

try {
  const rootUrl = await new Promise((done, reject) => {
    const timer = setTimeout(() => reject(new Error('Fixture server timed out')), 25000);
    const rl = createInterface({input: server.stdout});
    rl.once('line', line => { clearTimeout(timer); rl.close(); done(line.trim()); });
    server.once('error', reject);
  });

  const prototypeUrl = rootUrl.replace('/?', '/prototype?');
  console.log('Prototype URL:', prototypeUrl);

  browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});

  const screens = [
    { id: 'screen-1', name: 'first-mission', title: '1. First Mission (Read this brief)' },
    { id: 'screen-2', name: 'active-watch', title: '2. Active Streaming Test' },
    { id: 'screen-3', name: 'result-debrief', title: '3. Result & Recommended Improvement' },
    { id: 'screen-4', name: 'matched-comparison', title: '4. Matched Comparison & Decision' },
    { id: 'screen-5', name: 'storage-selection', title: '5. Storage & Model Selection' }
  ];

  for (const scr of screens) {
    console.log(`\nCapturing ${scr.title}...`);

    // Desktop: 1280x900
    await page.setViewportSize({width: 1280, height: 900});
    await page.goto(`${prototypeUrl}&screen=${scr.id}`);
    await page.waitForSelector(`#${scr.id}.active`, {timeout: 10000});
    // Wait for animation
    await page.waitForTimeout(400);

    const desktopPath = `work/prototype/${scr.name}-desktop.png`;
    await page.screenshot({path: desktopPath, fullPage: false});
    console.log(`Saved desktop screenshot: ${desktopPath}`);

    // Mobile: 390x844
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(`${prototypeUrl}&screen=${scr.id}`);
    await page.waitForSelector(`#${scr.id}.active`, {timeout: 10000});
    await page.waitForTimeout(400);

    // Verify no horizontal blowout
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    if (scrollWidth > clientWidth + 2) {
      console.warn(`[WARNING] Horizontal overflow detected on ${scr.id}: scrollWidth=${scrollWidth}, clientWidth=${clientWidth}`);
    } else {
      console.log(`Mobile responsive pass (scrollWidth=${scrollWidth}, clientWidth=${clientWidth})`);
    }

    const mobilePath = `work/prototype/${scr.name}-phone.png`;
    await page.screenshot({path: mobilePath, fullPage: false});
    console.log(`Saved mobile screenshot: ${mobilePath}`);
  }

  console.log('\nAll 10 prototype screenshots captured successfully in work/prototype/');
} catch (err) {
  console.error('Error during screenshot capture:', err);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  server.kill();
}
