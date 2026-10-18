import net from 'node:net';

const TOOLS = new Map([
  ['argos_evaluate', 'evaluation'], ['argos_compare', 'compare'], ['argos_log', 'log'],
]);

export function registerAdmission(api) {
  if (api.pluginConfig?.hostAdmission !== true) return null;
  const socketPath = process.env.ARGOS_CONTROLLER_SOCKET;
  const auth = process.env.ARGOS_CONTROLLER_SECRET;
  const turns = new Map();
  const bindings = new Map();

  function request(value, signal) {
    return new Promise((resolve, reject) => {
      const fail = () => reject(new Error('Host controller admission is unavailable.'));
      if (!socketPath || !auth) return fail();
      const socket = net.createConnection(socketPath);
      socket.setEncoding('utf8');
      let output = '';
      let bytes = 0;
      const abort = () => socket.destroy(new Error('Controller request cancelled'));
      if (signal?.aborted) abort();
      else signal?.addEventListener('abort', abort, {once: true});
      socket.setTimeout(31 * 60 * 1000, abort);
      socket.on('connect', () => socket.write(JSON.stringify({...value, auth}) + '\n'));
      socket.on('data', (chunk) => {
        bytes += Buffer.byteLength(chunk);
        if (bytes > 2 * 1024 * 1024) return abort();
        output += chunk;
        if (!output.endsWith('\n')) return;
        try { resolve(JSON.parse(output)); }
        catch { fail(); }
        socket.end();
      });
      socket.on('error', fail);
      socket.on('close', () => {
        signal?.removeEventListener('abort', abort);
        if (!output.endsWith('\n')) fail();
      });
    });
  }

  api.on('before_agent_run', async (_event, ctx) => {
    try {
      const value = await request({op:'begin', run_id:ctx.runId, session_id:ctx.sessionId,
        session_key:ctx.sessionKey, trigger:ctx.trigger});
      if (value.status !== 'admitted' || typeof value.turn_token !== 'string')
        return {outcome:'block', reason:'Host controller slot is not available'};
      turns.set(ctx.runId, value.turn_token);
      return {outcome:'pass'};
    } catch {
      return {outcome:'block', reason:'Host controller admission failed'};
    }
  });
  api.on('before_tool_call', (event, ctx) => {
    const runId = event.runId ?? ctx.runId;
    const callId = event.toolCallId ?? ctx.toolCallId;
    const token = turns.get(runId);
    if (!TOOLS.has(event.toolName) || !token || typeof callId !== 'string')
      return {block:true, blockReason:'This controller scope permits only admitted Argos host tools'};
    const prior = bindings.get(callId);
    if (prior && (prior.runId !== runId || prior.kind !== TOOLS.get(event.toolName)))
      return {block:true, blockReason:'Stale controller tool binding'};
    bindings.set(callId, {runId, token, kind:TOOLS.get(event.toolName)});
  });
  api.on('agent_end', async (_event, ctx) => {
    const token = turns.get(ctx.runId);
    if (!token) return;
    turns.delete(ctx.runId);
    for (const [key, binding] of bindings) if (binding.runId === ctx.runId) bindings.delete(key);
    try { await request({op:'ended', run_id:ctx.runId, turn_token:token}); }
    catch { /* Only the host supervisor may settle or release this scope. */ }
  });

  return {
    async execute(callId, kind, params, signal) {
      const binding = bindings.get(callId);
      bindings.delete(callId);
      if (!binding || binding.kind !== kind || turns.get(binding.runId) !== binding.token)
        throw new Error('Controller tool call has no current host admission.');
      const value = await request({op:'tool', run_id:binding.runId, turn_token:binding.token,
        call_id:callId, kind, params}, signal);
      if (value.status === 'busy') return {status:'busy', message:'Host workload needs attention',
        recovery_required:value.recovery_required === true};
      if (value.status !== 'completed') throw new Error('Host controller tool did not complete.');
      return value.value;
    }
  };
}
