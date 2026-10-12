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

test('file verification is not presented as a completed download', () => {
 assert.equal(c.autoClimbTally({phase:'acquire',download:{phase:'verifying',progress:{bytes_done:100,bytes_total:100}}}), 'Checking downloaded files…');
});

test('keeps the completed answer paired with its own question while next turn runs', () => {
 const v = {progress:{current:{id:'next',question:'Next question'}},
   receipts:[{id:'previous',kind:'control',question:'Previous question',reply:{text:'Real completed reply'},passed:true}]};
 const w = c.autoClimbWatch(v);
 assert.equal(w.current.question, 'Previous question');
 assert.equal(w.reply, 'Real completed reply');
 assert.equal(w.next, 'Next question');
 assert.equal(w.label, 'Last completed answer');
 assert.equal(w.verdict, 'Everyday reply passed');
 const oldSchema = c.autoClimbWatch({...v,receipts:[{id:'previous',reply:{text:'Do not misattribute me'}}]});
 assert.equal(oldSchema.current.id, 'next');
 assert.match(oldSchema.reply, /Waiting/);
});
