import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {observeRequests,hookRuntimeFetch} from '../scripts/native-chat-request-probe.mjs';

test('dispatcher runtime fetch is observed without changing its options or result',()=>{
  const root=mkdtempSync(join(tmpdir(),'argos-wire-runtime-'));
  try {
    const path=join(root,'metrics.json');
    let received;
    const result=Promise.resolve('fixture');
    const runtime={fetch:(...args)=>{received=args;return result;}};
    assert.equal(hookRuntimeFetch(runtime,path),true);
    const init={dispatcher:{fixture:true},body:JSON.stringify({options:{num_predict:32}})};
    assert.equal(runtime.fetch('http://127.0.0.1:11434/api/chat',init),result);
    assert.equal(received[1],init);
    const report=JSON.parse(readFileSync(path,'utf8'));
    assert.equal(report.num_predict,32);assert.equal(report.probe_loaded,true);
    assert.equal(hookRuntimeFetch({},path),false);
  } finally {rmSync(root,{recursive:true,force:true});}
});

test('probe preserves fetch arguments and response; exports only numeric options',()=>{
  const root=mkdtempSync(join(tmpdir(),'argos-wire-test-'));
  try {
    const path=join(root,'metrics.json');
    const result=Promise.resolve({fixture:true});
    let received;
    const probe=observeRequests((...args)=>{received=args;return result;},path);
    const url='http://127.0.0.1:11434/api/chat';
    const init={headers:{Authorization:'fictional-private-canary'},body:JSON.stringify({
      messages:[{content:'fictional-private-canary'}],think:false,
      options:{num_predict:32,num_ctx:32768,secret:'fictional-private-canary'},
      tools:[{description:'fictional-private-canary'}]})};
    assert.equal(probe(url,init),result);
    assert.equal(received[0],url);assert.equal(received[1],init);
    const raw=readFileSync(path,'utf8');
    assert.ok(!raw.includes('fictional-private-canary'));
    const report=JSON.parse(raw);
    assert.equal(report.num_predict,32);assert.equal(report.num_ctx,32768);
    assert.equal(report.request_count,1);assert.equal(report.think,false);
    assert.equal(report.requests.length,1);
    assert.equal(report.requests[0].num_predict,32);
    assert.equal(report.message_chars,24);
    probe(url,{body:'not json'});
    assert.equal(received[1].body,'not json');
    const after=JSON.parse(readFileSync(path,'utf8'));
    assert.equal(after.request_count,2);
    assert.equal(after.requests.length,2);
    assert.equal(after.requests[1].body_inspected,false);
  } finally {rmSync(root,{recursive:true,force:true});}
});

test('nonlocal requests are ignored and unsupported bodies are not consumed',()=>{
  const root=mkdtempSync(join(tmpdir(),'argos-wire-test-'));
  try {
    const path=join(root,'metrics.json');
    const original=()=>42;
    const probe=observeRequests(original,path);
    assert.equal(probe('https://example.invalid/api/chat',{body:'private'}),42);
    assert.ok(!existsSync(path));
    assert.equal(probe('http://127.0.0.1:11434/api/chat',{}),42);
    const report=JSON.parse(readFileSync(path,'utf8'));
    assert.equal(report.body_inspected,false);
    assert.equal(report.requests.length,1);
  } finally {rmSync(root,{recursive:true,force:true});}
});

test('append-only request log preserves observations from separate observers',()=>{
  const root=mkdtempSync(join(tmpdir(),'argos-wire-log-'));
  try {
    const path=join(root,'metrics.jsonl');
    const result=Promise.resolve('fixture');
    const url='http://127.0.0.1:11434/api/chat';
    const first=observeRequests(()=>result,null,path);
    const second=observeRequests(()=>result,null,path);
    first(url,{body:JSON.stringify({messages:[{content:'private-canary'}],options:{num_predict:32}})});
    second(url,{body:JSON.stringify({messages:[{content:'private-canary'}],options:{num_predict:32}})});
    const raw=readFileSync(path,'utf8');
    assert.ok(!raw.includes('private-canary'));
    const events=raw.trim().split('\n').map(line=>JSON.parse(line));
    assert.equal(events.length,2);
    assert.deepEqual(events.map(row=>row.kind),['request','request']);
    assert.deepEqual(events.map(row=>row.num_predict),[32,32]);
  } finally {rmSync(root,{recursive:true,force:true});}
});
