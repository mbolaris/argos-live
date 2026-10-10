// Integrated interaction and visual acceptance for the focused mission layout:
// Mission → Watch → Improve → approved experiment → matched retest → before/after → Keep/Restore.
// Fixture inference only; never evidence of model quality or physical Firefox acceptance.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {resolve} from 'node:path';
import {createInterface} from 'node:readline';
import {mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require = createRequire(resolve(process.env.ARGOS_BROWSER_RUNTIME || 'work/compatibility-runtime/package.json'));
const {chromium} = require('playwright-core');
const server = spawn(process.env.ARGOS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-u', 'scripts/serve-journey-fixture.py'], {stdio:['pipe','pipe','inherit'],
  env:{...process.env, ARGOS_FIXTURE_STREAM_DELAY:'0.05'}});
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
  const both=async (name,prepare)=>{
    for (const [suffix,width,height] of [['desktop',1280,900],['phone',390,844]]) {
      await page.setViewportSize({width,height});
      if (prepare) await prepare();
      await shot(`${name}-${suffix}`);
    }
    await page.setViewportSize({width:1280,height:900});
  };
  const scrollTo=id=>page.evaluate(id=>{const el=document.getElementById(id);window.scrollTo(0,el.getBoundingClientRect().top+scrollY-12);},id);
  await page.goto(url);
  await page.locator('#cc-next-go').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.getElementById('cc-next-title').textContent==='Read this brief');
  for (const id of ['workbench','curriculum-map','full-skill-map','example-missions']) {
    assert.equal(await page.locator('#'+id).evaluate(el=>el.open),false,`${id} starts collapsed`);
  }
  assert.equal(await page.locator('#cc-receipt').isVisible(),false,'No empty result panel');
  assert.equal(await page.locator('#session-watch').getAttribute('aria-disabled'),'true');
  const ids=await page.locator('[id]').evaluateAll(nodes=>nodes.map(n=>n.id));
  assert.equal(new Set(ids).size,ids.length,'Unique control IDs');
  await both('mission');
  await page.setViewportSize({width:390,height:844});
  const start=await page.locator('#cc-next-go').boundingBox();
  assert.ok(start.y+start.height<=844,'Phone Start stays above fold');
  await page.setViewportSize({width:1280,height:900});

  // ---- Watch: passage beside the question, readable answer, plain progress, Stop.
  await page.locator('#cc-next-go').click();
  await page.waitForFunction(()=>document.getElementById('command-center').dataset.watching==='true');
  assert.equal(await page.locator('#cc-next').isVisible(),false,'No competing mission while watching');
  assert.equal(await page.locator('#lab-cancel').isVisible(),true,'Stop remains in Watch');
  assert.equal(await page.locator('#arena-run-details').evaluate(el=>el.open),false,'Model/recipe details are on request');
  await page.waitForFunction(()=>{
    const raw=document.getElementById('arena-current-raw').textContent;
    const text=document.getElementById('arena-current-stream').textContent;
    const passage=document.getElementById('arena-current-passage').dataset.text||'';
    return raw.includes('"answer"') && text.length>2 && !text.startsWith('{') && passage.length>100 && document.getElementById('arena-source-details').open;
  },null,{timeout:30000});
  const passage=await page.locator('#arena-current-passage').evaluate(el=>el.dataset.text);
  assert.ok(!passage.includes('QUESTION:') && !passage.includes('Respond with'),'Passage excludes question and schema');
  assert.match(await page.locator('#arena-progress-label').textContent(),/^\d+ of \d+ responses done$/);
  // Highlight an exact returned quote once one arrives.
  await page.waitForFunction(()=>document.querySelector('#arena-current-passage mark'),null,{timeout:30000});
  assert.ok(await page.locator('#arena-current-passage').evaluate(el=>el.querySelector('mark') && el.dataset.text.includes(el.querySelector('mark').textContent)),
    'Highlighted text is an exact passage quotation');
  await both('watch',async()=>{
    // Phone keeps the passage one tap away; wide screens keep it open beside the question.
    const phone=(await page.viewportSize()).width<900;
    await page.locator('#arena-source-details').evaluate((el,phone)=>{el.open=!phone;},phone);
    await scrollTo('arena');
  });
  const passageBox=await page.locator('#arena-source-details').boundingBox();
  const questionBox=await page.locator('#arena-current-question').boundingBox();
  assert.ok(passageBox.x+passageBox.width<=questionBox.x+1,'Desktop passage sits beside the question');

  // ---- Improve: plain result, accurate counts, one evidence-based experiment, real debrief.
  await page.waitForFunction(()=>document.getElementById('arena-phase-badge').textContent==='COMPLETED',null,{timeout:60000});
  await page.waitForFunction(()=>document.getElementById('session-result').getAttribute('aria-disabled')==='false');
  await page.waitForFunction(()=>!document.getElementById('improve-next').hidden && !document.getElementById('cc-debrief').hidden,null,{timeout:20000});
  assert.equal(await page.locator('#cc-receipt-title').textContent(),'23 of 24 correct');
  assert.match(await page.locator('#cc-count-note').textContent(),/32 responses: 24 scored questions, plus 8 summaries/);
  assert.match(await page.locator('#arena-summary-detail').textContent(),/23 of 24 scored questions correct/);
  assert.equal(await page.locator('#improve-next').getAttribute('data-kind'),'format');
  assert.match(await page.locator('#improve-why').textContent(),/1 of 24 scored answer was in the wrong answer format/);
  assert.equal(await page.locator('#receipt-change').isHidden(),true,'Proposed experiment is not repeated');
  assert.match(await page.locator('#cc-debrief-note').textContent(),/^Written by fixture:latest after scoring\./);
  await page.locator('#session-result').click();
  await page.waitForFunction(()=>document.getElementById('cc-receipt').getBoundingClientRect().top<140);
  await both('result',()=>scrollTo('cc-receipt'));

  // ---- Approval before anything runs.
  let starts=0;page.on('request',r=>{if(r.url().endsWith('/api/lab/start-documents'))starts++;});
  await page.locator('#improve-go').click();
  await page.locator('#recipe-modal').waitFor({state:'visible'});
  assert.equal(starts,0,'Reviewing does not start the experiment');
  assert.equal(await page.locator('.recipe-lead').textContent(),'Add one instruction, repeat the same test, compare results.');
  assert.equal(await page.locator('#recipe-modal .recipe-protection-notice').evaluate(el=>el.open),false,'Protection detail is collapsed');
  await both('approve');
  await page.locator('#recipe-close').click();
  assert.equal(starts,0,'Not now does not start the experiment');
  await page.locator('#improve-go').click();
  await page.locator('#recipe-run').click();
  await page.waitForFunction(()=>document.getElementById('command-center').dataset.watching==='true',null,{timeout:15000});
  assert.equal(starts,1,'Approval starts exactly one retest');

  // ---- Matched retest → before/after in Improve → Keep → Restore.
  await page.waitForFunction(()=>document.querySelector('#improve-comparison #experiment-recommendation'),null,{timeout:90000});
  await page.waitForFunction(()=>document.getElementById('command-center').dataset.watching==='false');
  assert.equal(await page.locator('#experiment-comparison .experiment-card').count(),0,'Comparison is not duplicated in records');
  const comparison=await page.locator('#improve-comparison').textContent();
  assert.match(comparison,/Correct answers\s*23 of 24 → 24 of 24/);
  assert.match(comparison,/Wrong answer format\s*1 → 0/);
  assert.equal(await page.locator('#exp-action-primary').textContent(),'Keep for lab tests');
  assert.equal(await page.locator('#exp-action-secondary').textContent(),'Restore standard instructions');
  assert.match(comparison,/Lab tests only\. Your everyday assistant doesn’t use this instruction/);
  assert.equal(await page.locator('#improve-next').isHidden(),true,'No new proposal over an undecided experiment');
  await page.locator('#session-result').click();
  await both('compare',()=>scrollTo('improve-comparison'));
  await page.locator('#exp-action-primary').click();
  await page.waitForFunction(()=>document.getElementById('recommendation-status').textContent.includes('Your everyday assistant is unchanged'));
  assert.equal((await page.evaluate(()=>api('/api/lab/recipes'))).selected?.preset,'concise');
  await both('kept',()=>scrollTo('improve-comparison'));
  await page.locator('#exp-action-secondary').click();
  await page.waitForFunction(()=>document.getElementById('recommendation-status').textContent.includes('Restored standard instructions'));
  assert.equal((await page.evaluate(()=>api('/api/lab/recipes'))).selected,null);

  // Jumping to a nested destination must reveal its closed ancestors.
  await page.locator('.setup-link').click();
  assert.equal(await page.locator('#workbench').evaluate(el=>el.open),true);
  await page.locator('#models-title').waitFor({state:'visible'});
  for (const width of [320,390,1280]) {
    await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`No overflow at ${width}`);
  }
  // A new run's speed check never shows the previous run's passage (seen in shipped Firefox).
  assert.ok(await page.locator('#arena-current-passage').evaluate(el=>el.dataset.text.length>0),'Passage from the finished run is present');
  assert.equal(await page.evaluate(()=>{renderArenaState({total:0},true,'speed','fixture:latest',0);
    return document.getElementById('arena-source-details').hidden && !document.getElementById('arena-current-passage').dataset.text;}),true,
    'Speed check hides the previous passage');
  const finalIds=await page.locator('[id]').evaluateAll(nodes=>nodes.map(n=>n.id));
  assert.equal(new Set(finalIds).size,finalIds.length,'Unique control IDs after the experiment');
  assert.deepEqual(errors,[]);
  console.log('PASS: mission, watch with passage, plain result, approved experiment, matched retest, before/after, keep and restore; fixture only.');
} finally {if(browser)await browser.close();server.stdin.end();server.kill();}
