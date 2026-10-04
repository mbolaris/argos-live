import test from 'node:test';
import assert from 'node:assert/strict';
import {parsePins,stableRelease,sha256Asset,patchRelease} from '../scripts/check-upstream.mjs';
test('pins retain base64 padding and ignore comments',()=>{
  assert.deepEqual(parsePins('# comment\nOPENCLAW_INTEGRITY=sha512-abc==\r\nNODE_SHA256=abc\n'),
    {OPENCLAW_INTEGRITY:'sha512-abc==',NODE_SHA256:'abc'});
});
test('unstable and draft releases cannot be promoted',()=>{
  for(const r of [{tag_name:'v1.2.3-beta.1'},{tag_name:'v1.2.3',prerelease:true},{tag_name:'v1.2.3',draft:true}])
    assert.throws(()=>stableRelease(r));
  assert.equal(stableRelease({tag_name:'v2026.9.8'}),'2026.9.8');
});
test('missing checksum cannot become a candidate pin',()=>{
  assert.throws(()=>sha256Asset({assets:[{name:'x'}]},'x'));
  assert.equal(sha256Asset({assets:[{name:'x',digest:'sha256:'+'a'.repeat(64)}]},'x'),'a'.repeat(64));
});
test('Node discovery cannot silently change major',()=>{
  assert.equal(patchRelease([{version:'v28.0.0'},{version:'v26.11.0'}],'26.10.0').version,'v26.11.0');
  assert.throws(()=>patchRelease([{version:'v28.0.0'}],'26.10.0'));
});
