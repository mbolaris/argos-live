import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../runtime/argoslive/web/static/app.js',import.meta.url),'utf8');
const context=vm.createContext({});
vm.runInContext(source.slice(source.indexOf('function arenaAnswerPreview('),source.indexOf('function presentArenaAnswer(')),context);
test('reading answer and quote are readable while preserving meaning',()=>{
  assert.equal(context.arenaAnswerPreview('{"answer":"35 minutes","quote":"The crossing takes 35 minutes."}'),'35 minutes\n\nSupporting quote:\n“The crossing takes 35 minutes.”');
});
test('answer prefix decodes received escapes without inventing a completion',()=>{
  assert.equal(context.arenaAnswerPreview('{"answer":"A \\"quoted\\" wor'),'A "quoted" wor');
  assert.equal(context.arenaAnswerPreview('{"answer":"\\u00'),'Receiving answer text…');
});
test('unrecognized or plain output stays inspectable rather than being repaired',()=>{
  for(const text of ['A plain summary','{"unexpected":42}','{broken','<img src=x onerror=bad()>'])assert.equal(context.arenaAnswerPreview(text),text);
});
test('not-stated status is distinct from an answer',()=>{
  assert.equal(context.arenaAnswerPreview('{"status":"not_stated"}'),'Not stated in the passage.');
  assert.equal(context.arenaAnswerPreview('{"status":"not_stated","answer":""}'),'Not stated in the passage.');
});
test('an envelope that has not reached its answer shows progress, not JSON',()=>{
  assert.equal(context.arenaAnswerPreview('{"status": "answered", "a'),'Receiving answer text…');
  assert.equal(context.arenaAnswerPreview('{"status": "not_stated", "answer": "", "quo'),'Not stated in the passage.');
  assert.equal(context.arenaAnswerPreview('{"status": "not_stated", "answer": "Ye'),'Ye');
});
