// Disposable native smoke only. Observe numeric request options without changing
// transport, body, headers, prompts or responses. Never export request content.
import {writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';

export function observeRequests(original, reportPath) {
  let count=0;
  return function(...args) {
    try {
      const [input,init]=args;
      const url=new URL(typeof input==='string' || input instanceof URL ? input : input?.url);
      if (url.origin==='http://127.0.0.1:11434' && url.pathname==='/api/chat') {
        count++;
        const metrics={probe_loaded:true,request_count:count,body_inspected:false};
        // The pinned provider passes a serialized JSON body. Do not consume a
        // Request stream or clone a response if a different call shape appears.
        if (typeof init?.body==='string' && Buffer.byteLength(init.body)<=2*1024**2) {
          const body=JSON.parse(init.body);
          metrics.body_inspected=true;
          metrics.request_bytes=Buffer.byteLength(init.body);
          const options=body?.options;
          for (const key of ['num_predict','num_ctx']) {
            metrics[key+'_present']=typeof options?.[key]==='number';
            if (Number.isFinite(options?.[key]) && options[key]>=-2 && options[key]<=1e12)
              metrics[key]=options[key];
          }
          if (typeof body?.think==='boolean') metrics.think=body.think;
          if (Array.isArray(body?.messages)) metrics.message_chars=body.messages.reduce(
            (n,row)=>n+(typeof row?.content==='string'?row.content.length:0),0);
          metrics.tool_schema_chars=JSON.stringify(body?.tools??[]).length;
        }
        writeFileSync(reportPath,JSON.stringify(metrics),{mode:0o600});
      }
    } catch (_) { /* Diagnostics must not change the native request outcome. */ }
    return original.apply(this,args);
  };
}

export function hookRuntimeFetch(runtime,reportPath) {
  if (typeof runtime?.fetch!=='function') return false;
  runtime.fetch=observeRequests(runtime.fetch,reportPath);
  return true;
}

if (process.env.ARGOS_NATIVE_REQUEST_REPORT) {
  const path=process.env.ARGOS_NATIVE_REQUEST_REPORT;
  globalThis.fetch=observeRequests(globalThis.fetch,path);
  let runtimeHooked=false;
  try {
    // OpenClaw's dispatcher-aware guarded path uses the pinned dependency's
    // fetch directly. Resolve from that exact CLI entry, not this repo's deps.
    const runtime=createRequire(process.env.ARGOS_NATIVE_OPENCLAW_ENTRY)('undici');
    runtimeHooked=hookRuntimeFetch(runtime,path);
  } catch (_) { /* Explicit activation report distinguishes an unavailable hook. */ }
  try {writeFileSync(path,JSON.stringify({probe_loaded:true,
    runtime_fetch_hooked:runtimeHooked,request_count:0,body_inspected:false}),{mode:0o600});}
  catch (_) { /* Diagnostics must not change the fixture outcome. */ }
}
