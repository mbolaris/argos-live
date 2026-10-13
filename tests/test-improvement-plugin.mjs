import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';

test('plugin tools call the installed Argos benchmark commands', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'argos-plugin-'));
  const executable = path.join(directory, 'fake-argos.mjs');
  const capture = path.join(directory, 'args.json');
  const priorBin = process.env.ARGOS_BIN;
  const priorBinArgs = process.env.ARGOS_BIN_ARGS;
  const priorCapture = process.env.ARGOS_CAPTURE;
  try {
    await writeFile(executable, `import fs from 'node:fs';
const args = process.argv.slice(2);
fs.writeFileSync(process.env.ARGOS_CAPTURE, JSON.stringify(args));
if (args[1] === 'openclaw') {
  console.error(JSON.stringify({phase:'scored', completed:1, total:20, receipt:{score:true, output:'fixture answer'}}));
  console.log(JSON.stringify({path:'/private/fixture-result.json', result:{
    id:'a'.repeat(32), suite:fs.existsSync(process.env.ARGOS_CAPTURE+'.raw')?'quick':'openclaw-quick', suite_version:'argos-openclaw-ability/quick/fixture1', state:'completed',
    settings:{suite_sha256:'b'.repeat(64),execution_path:'openclaw gateway; fresh session per task'}, prompt_fingerprint:{workspace_agents_sha256:'c'.repeat(64)},
    summary:{correct:18,total:20}, coverage:{completed:20,total:20,complete:true}, elapsed_seconds:12
  }}));
} else {
  console.log(JSON.stringify({kind:'ability',suite_version:fs.existsSync(process.env.ARGOS_CAPTURE+'.raw')?'raw/quick/1':'argos-openclaw-ability/quick/fixture1',settings:{execution_path:'openclaw gateway; fresh session per task'},workspace_agents_changed:false, rows:[]}));
}
`);
    process.env.ARGOS_BIN = process.execPath;
    process.env.ARGOS_BIN_ARGS = JSON.stringify([executable]);
    process.env.ARGOS_CAPTURE = capture;
    const pluginPath = pathToFileURL(path.resolve('openclaw-plugin/argos-improve/index.js')).href;
    const { default: register } = await import(`${pluginPath}?test=${Date.now()}`);
    const tools = new Map();
    register({ registerTool(tool) { tools.set(tool.name, tool); } });

    const progress = [];
    const evaluated = await tools.get('argos_evaluate').execute('eval', { suite: 'quick' }, undefined,
      (event) => progress.push(event));
    assert.match(evaluated.content[0].text, /18\/20 passed/);
    assert.equal(evaluated.details.suite_sha256, 'b'.repeat(64));
    assert.equal(progress.length, 1);
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'openclaw', '--suite', 'quick', '--json']);

    await tools.get('argos_compare').execute('compare', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    });
    assert.deepEqual(JSON.parse(await readFile(capture, 'utf8')),
      ['bench', 'results', '--compare', '1'.repeat(32), '2'.repeat(32), '--json']);
    await writeFile(capture + '.raw', 'raw-model fixture');
    await assert.rejects(tools.get('argos_evaluate').execute('raw', { suite: 'quick' }),
      /Raw model runs do not test assistant instructions/);
    await assert.rejects(tools.get('argos_compare').execute('raw-compare', {
      baseline_id: '1'.repeat(32), candidate_id: '2'.repeat(32)
    }), /Raw model runs do not test assistant instructions/);
  } finally {
    if (priorBin === undefined) delete process.env.ARGOS_BIN;
    else process.env.ARGOS_BIN = priorBin;
    if (priorBinArgs === undefined) delete process.env.ARGOS_BIN_ARGS;
    else process.env.ARGOS_BIN_ARGS = priorBinArgs;
    if (priorCapture === undefined) delete process.env.ARGOS_CAPTURE;
    else process.env.ARGOS_CAPTURE = priorCapture;
    await rm(directory, { recursive: true, force: true });
  }
});
