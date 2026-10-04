#!/usr/bin/env node
// Discovery only: never changes accepted pins or running software.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
export function parsePins(text) {
  return Object.fromEntries(text.split(/\r?\n/).filter(l=>/^[A-Z][A-Z_0-9]*=/.test(l)).map(l=>{
    const at=l.indexOf('='); return [l.slice(0,at),l.slice(at+1)];
  }));
}
export function stableRelease(r) {
  if(r.draft || r.prerelease || !/^v?\d+\.\d+\.\d+$/.test(r.tag_name))
    throw new Error('Upstream release is not stable');
  return r.tag_name.replace(/^v/,'');
}
export function sha256Asset(r,name) {
  const a=r.assets.find(a=>a.name===name);
  if(!/^sha256:[a-f0-9]{64}$/.test(a?.digest || '')) throw new Error('Missing SHA256 for '+name);
  return a.digest.slice(7);
}
export function patchRelease(releases,current) {
  const major=current.split('.')[0];
  const r=releases.find(r=>r.version.startsWith('v'+major+'.') && !r.version.includes('-'));
  if(!r) throw new Error('Pinned Node major absent upstream');
  return r;
}
async function request(url,json=true) {
  const headers={'User-Agent':'argos-live-release-check','Accept':'application/json'};
  if(url.startsWith('https://api.github.com/') && process.env.GITHUB_TOKEN)
    headers.Authorization='Bearer '+process.env.GITHUB_TOKEN;
  const response=await fetch(url,{headers,signal:AbortSignal.timeout(30000)});
  if(!response.ok) throw new Error(url+': HTTP '+response.status);
  return json?response.json():response.text();
}
async function main() {
  const root=fileURLToPath(new URL('../',import.meta.url));
  const out=path.resolve(process.argv[2] || path.join(root,'work/upstream-report'));
  const pins=parsePins(await fs.readFile(path.join(root,'versions.env'),'utf8'));
  const [pkg,claw,ollama,nodes]=await Promise.all([
    request('https://registry.npmjs.org/openclaw/latest'),
    request('https://api.github.com/repos/openclaw/openclaw/releases/latest'),
    request('https://api.github.com/repos/ollama/ollama/releases/latest'),
    request('https://nodejs.org/dist/index.json')]);
  const clawVersion=stableRelease(claw);
  if(pkg.version!==clawVersion || !/^sha512-[A-Za-z0-9+/]+=*$/.test(pkg.dist?.integrity || ''))
    throw new Error('OpenClaw registry/release disagreement or missing integrity');
  const ollamaVersion=stableRelease(ollama);
  const node=patchRelease(nodes,pins.NODE_VERSION);
  const sums=await request('https://nodejs.org/dist/'+node.version+'/SHASUMS256.txt',false);
  const nodeHash=sums.split(/\r?\n/).find(l=>l.endsWith('  node-'+node.version+'-linux-x64.tar.xz'))?.split(/\s+/)[0];
  if(!/^[a-f0-9]{64}$/.test(nodeHash || '')) throw new Error('Missing Node checksum');
  const candidates={...pins,OPENCLAW_VERSION:clawVersion,OPENCLAW_INTEGRITY:pkg.dist.integrity,
    OLLAMA_VERSION:ollamaVersion,OLLAMA_SHA256:sha256Asset(ollama,'ollama-linux-amd64.tar.zst'),
    NODE_VERSION:node.version.slice(1),NODE_SHA256:nodeHash};
  const changed=['OPENCLAW_VERSION','OLLAMA_VERSION','NODE_VERSION'].filter(k=>pins[k]!==candidates[k]);
  const s=pins.DEBIAN_SNAPSHOT;
  const snapshotAgeDays=Math.floor((Date.now()-Date.UTC(+s.slice(0,4),+s.slice(4,6)-1,+s.slice(6,8)))/86400000);
  const report={checkedAt:new Date().toISOString(),status:'discovery-only',changed,current:pins,candidate:candidates,
    openclawNodeRequirement:pkg.engines?.node,sources:{openclaw:claw.html_url,ollama:ollama.html_url,node:'https://nodejs.org/dist/index.json'},
    nodePolicy:'Latest patch in pinned major; LTS/major transition requires compatibility review',
    debian:{snapshotAgeDays,securityConfigured:!!pins.DEBIAN_SECURITY_SNAPSHOT,refreshDue:snapshotAgeDays>7,
      packageUpdateCheck:'Not performed: clean signed APT resolution and package-manifest diff required'},
    promotion:'Pending lock regeneration, audit, clean ISO build, VM tests and physical acceptance'};
  await fs.mkdir(out,{recursive:true});
  await fs.writeFile(path.join(out,'upstream.json'),JSON.stringify(report,null,2)+'\n');
  await fs.writeFile(path.join(out,'versions.candidate.env'),'# DISCOVERY ONLY: not accepted pins; Debian snapshots need refresh/review.\n'+Object.entries(candidates).map(([k,v])=>k+'='+v).join('\n')+'\n');
  const summary='# Argos upstream check\n\n'+['OpenClaw: '+pins.OPENCLAW_VERSION+' → '+clawVersion,
    'Ollama: '+pins.OLLAMA_VERSION+' → '+ollamaVersion,'Node: '+pins.NODE_VERSION+' → '+candidates.NODE_VERSION,
    'Debian snapshot age: '+snapshotAgeDays+' days; security snapshot configured: '+report.debian.securityConfigured,
    'Candidate changes: '+(changed.join(', ') || 'none'),
    'Discovery only. Debian package resolution and release acceptance remain required.'].map(l=>'- '+l).join('\n')+'\n';
  await fs.writeFile(path.join(out,'summary.md'),summary);
  if(process.env.GITHUB_STEP_SUMMARY) await fs.appendFile(process.env.GITHUB_STEP_SUMMARY,summary);
  console.log(summary);
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url))
  main().catch(e=>{console.error(e.message);process.exitCode=1;});
