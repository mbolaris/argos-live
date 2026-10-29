// Disposable native smoke only. Observe numeric request options without changing
// transport, body, headers, prompts or responses. Never export request content.
import {writeFileSync} from 'node:fs';
import {createRequire} from 'node:module';

const MAX_RECORDED_REQUESTS = 64;
const reports = new Map();

function reportState(reportPath) {
  let state=reports.get(reportPath);
  if (!state) {
    state={request_count:0,requests:[],runtime_fetch_hooked:false};
    reports.set(reportPath,state);
  }
  return state;
}

function persist(reportPath,state,last={}) {
  try {
    writeFileSync(reportPath,JSON.stringify({probe_loaded:true,
      runtime_fetch_hooked:state.runtime_fetch_hooked,
      request_count:state.request_count,
      requests:state.requests,
      requests_truncated:state.request_count>MAX_RECORDED_REQUESTS,
      ...last}),{mode:0o600});
  } catch (_) { /* Diagnostics must not change the native request outcome. */ }
}

export function observeRequests(original, reportPath) {
  const state=reportState(reportPath);
  return function(...args) {
    try {
      const [input,init]=args;
      const url=new URL(typeof input==='string' || input instanceof URL ? input : input?.url);
      if (url.origin==='http://127.0.0.1:11434' && url.pathname==='/api/chat') {
        state.request_count++;
        const metrics={body_inspected:false};
        // The pinned provider passes a serialized JSON body. Do not consume a
        // Request stream or clone a response if a different call shape appears.
        try {
          if (typeof init?.body==='string' && Buffer.byteLength(init.body)<=2*1024**2) {
            const body=JSON.parse(init.body);
            metrics.body_inspected=true;
            metrics.request_bytes=Buffer.byteLength(init.body);
            const options=body?.options;
            if (typeof options?.temperature==='number' && Number.isFinite(options.temperature) &&
                options.temperature>=0 && options.temperature<=2) metrics.temperature=options.temperature;
            for (const key of ['num_predict','num_ctx']) {
              metrics[key+'_present']=typeof options?.[key]==='number';
              if (Number.isFinite(options?.[key]) && options[key]>=-2 && options[key]<=1e12)
                metrics[key]=options[key];
            }
            if (typeof body?.think==='boolean') metrics.think=body.think;
            if (Array.isArray(body?.messages)) metrics.message_chars=body.messages.reduce(
              (n,row)=>n+(typeof row?.content==='string'?row.content.length:0),0);
            metrics.tool_schema_chars=JSON.stringify(body?.tools??[]).length;
            const allowed = new Set(['start','status','item','answer','continue','submit','feedback'].map(name=>'argos_proctor_'+name));
            metrics.proctor_tools = [...new Set((Array.isArray(body?.tools)?body.tools:[])
              .map(tool=>tool?.function?.name).filter(name=>allowed.has(name)))].sort();
            metrics.tool_result_messages = Array.isArray(body?.messages) ? body.messages.filter(row=>row?.role==='tool').length : 0;
          }
        } catch (_) { /* Record the request as uninspected; the budget gate will fail closed. */ }
        if (state.requests.length<MAX_RECORDED_REQUESTS) state.requests.push(metrics);
        // Preserve the most recent request's bounded metadata for existing
        // smoke receipts, while retaining every request needed by the budget gate.
        persist(reportPath,state,metrics);
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
  const state=reportState(path);
  state.runtime_fetch_hooked=runtimeHooked;
  persist(path,state,{body_inspected:false});
}
