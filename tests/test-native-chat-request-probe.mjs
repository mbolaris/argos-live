import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,existsSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {observeRequests} from '../scripts/native-chat-request-probe.mjs';

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
    assert.equal(report.message_chars,24);
    probe(url,{body:'not json'});
    assert.equal(received[1].body,'not json');
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
    assert.equal(JSON.parse(readFileSync(path,'utf8')).body_inspected,false);
  } finally {rmSync(root,{recursive:true,force:true});}
});
