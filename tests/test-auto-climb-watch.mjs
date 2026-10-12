import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const s = readFileSync(new URL('../runtime/argoslive/web/static/app.js', import.meta.url), 'utf8');
const c = vm.createContext({});
vm.runInContext(s.slice(s.indexOf('function autoClimbAnswer('), s.indexOf('function renderAutoClimb(')), c);
test('renders answer text and suppresses stale previous answer', () => {
 assert.equal(c.autoClimbAnswer({current:{id:'a'},latest:{id:'a',reply:{text:'An actual answer'}}}), 'An actual answer');
 assert.match(c.autoClimbAnswer({current:{id:'b'},latest:{id:'a',reply:{text:'Old'}}}), /Waiting/);
});
test('bounded completed count and separate download progress', () => {
 assert.equal(c.autoClimbTally({progress:{done:8,total:8}}), '8 / 8 answers finished');
 assert.equal(c.autoClimbTally({phase:'acquire',download:{progress:{bytes_done:50,bytes_total:100}}}), '50% downloaded');
});
test('missing quote is explained without changing score', () => {
 assert.equal(c.autoClimbReceipt({passed:false,checks:{answer_present:true,exact_quote:false}}), 'Correct answer, missing quote');
});
