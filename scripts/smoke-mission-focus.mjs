// Integrated interaction and visual acceptance for the focused mission layout.
// Fixture inference only; never evidence of model quality or physical Firefox acceptance.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const {chromium} = require('playwright-core');
const server = spawn(process.env.ARGOS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-u', 'scripts/serve-journey-fixture.py'], {stdio:['pipe','pipe','inherit']});
let browser;
try {
  const url = await new Promise((done,reject) => {
    const timer=setTimeout(()=>reject(new Error('Fixture timeout')),25000);
    createInterface({input:server.stdout}).once('line',line=>{clearTimeout(timer);done(line.trim());});
    server.once('error',reject);
  });
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/style.css?*',async route=>{
    const response=await route.fetch();
    await route.fulfill({response,body:await response.text()+'\n.simulation-banner{position:fixed;bottom:0;left:0;right:0;z-index:10000;background:#453329;color:#ffe2b0;text-align:center;font:11px system-ui;padding:5px}'});
  });
  await mkdir('output/playwright/mission-focus',{recursive:true});
  const shot=async name=>{
    await page.evaluate(()=>{
      if(document.querySelector('.simulation-banner'))return;
      const banner=document.createElement('div');banner.className='simulation-banner';
      banner.textContent='SIMULATED PREVIEW · NOT REAL MODEL INFERENCE';document.body.prepend(banner);
    });
    await page.screenshot({path:`output/playwright/mission-focus/${name}.png`});
  };
  await page.goto(url);
  await page.locator('#cc-next-go').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.getElementById('cc-next-title').textContent==='Read this brief');
  for (const id of ['workbench','curriculum-map','full-skill-map','example-missions']) {
    assert.equal(await page.locator('#'+id).evaluate(el=>el.open),false,`${id} starts collapsed`);
  }
  assert.equal(await page.locator('#cc-receipt').isVisible(),false,'No empty result panel');
  assert.equal(await page.locator('#session-watch').getAttribute('aria-disabled'),'true');
  const ids=await page.locator('[id]').evaluateAll(nodes=>nodes.map(n=>n.id));
  assert.equal(new Set(ids).size,ids.length,'Unique control IDs after moving Watch');
  await shot('mission-desktop');
  await page.setViewportSize({width:390,height:844});
  await shot('mission-phone');
  const start=await page.locator('#cc-next-go').boundingBox();
  assert.ok(start.y+start.height<=844,'Phone Start stays above fold');
  await page.locator('#cc-next-go').click();
  await page.waitForFunction(()=>document.getElementById('command-center').dataset.watching==='true');
  assert.equal(await page.locator('#cc-next').isVisible(),false,'No competing mission while watching');
  assert.equal(await page.locator('#lab-cancel').isVisible(),true,'Stop remains in Watch');
  await page.waitForFunction(()=>{
    const raw=document.getElementById('arena-current-raw').textContent;
    const text=document.getElementById('arena-current-stream').textContent;
    return raw.includes('"answer"') && text.length>2 && !text.startsWith('{');
  },null,{timeout:30000});
  await shot('watch-phone');
  await page.setViewportSize({width:1280,height:900});
  await shot('watch-desktop');
  await page.waitForFunction(()=>document.getElementById('arena-phase-badge').textContent==='COMPLETED',null,{timeout:60000});
  await page.waitForFunction(()=>document.getElementById('session-result').getAttribute('aria-disabled')==='false');
  await page.locator('#session-result').click();
  await page.locator('#cc-receipt').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.getElementById('cc-receipt').getBoundingClientRect().top<140);
  await shot('result-desktop');
  await page.setViewportSize({width:390,height:844});
  await page.locator('#session-result').click();
  await page.waitForFunction(()=>document.getElementById('cc-receipt').getBoundingClientRect().top<140);
  await shot('result-phone');
  await page.locator('#receipt-secondary-options > summary').click();
  await page.evaluate(()=>refreshCommand());
  assert.equal(await page.locator('#receipt-secondary-options').evaluate(el=>el.open),true,'Polling preserves opened result options');
  await page.locator('#receipt-change').click();
  await page.locator('#recipe-modal').waitFor({state:'visible'});
  await page.locator('#recipe-close').click();
  // Jumping to a nested destination must reveal its closed ancestors.
  await page.locator('.setup-link').click();
  assert.equal(await page.locator('#workbench').evaluate(el=>el.open),true);
  await page.locator('#models-title').waitFor({state:'visible'});
  for (const width of [320,390,1280]) {
    await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`No overflow at ${width}`);
  }
  assert.deepEqual(errors,[]);
  console.log('PASS: focused mission, live watch, result, setup disclosure, phone Start, no overflow; fixture only.');
} finally {if(browser)await browser.close();server.stdin.end();server.kill();}
