import net from 'node:net';

const TOOLS = new Map([
  ['argos_evaluate', 'evaluation'], ['argos_compare', 'compare'], ['argos_log', 'log'],
  ['argos_evaluate_wait', 'evaluation_wait'],
  ['argos_evaluate_status', 'evaluation_status'],
  ['argos_inspect', 'inspect'], ['argos_edit_instructions', 'edit'], ['argos_resolve_instructions', 'resolve'],
  ['argos_proctor_start', 'proctor_start'], ['argos_proctor_status', 'proctor_status'],
  ['argos_proctor_item', 'proctor_item'], ['argos_proctor_answer', 'proctor_answer'],
  ['argos_proctor_continue', 'proctor_continue'], ['argos_proctor_submit', 'proctor_submit'],
  ['argos_proctor_feedback', 'proctor_feedback'],
]);

export function registerAdmission(api) {
  if (api.pluginConfig?.hostAdmission !== true) return null;
  const socketPath = process.env.ARGOS_CONTROLLER_SOCKET;
  const auth = process.env.ARGOS_CONTROLLER_SECRET;
  const turns = new Map();
  const bindings = new Map();

  function request(value, signal, onUpdate) {
    return new Promise((resolve, reject) => {
      const fail = () => reject(new Error('Host controller admission is unavailable.'));
      if (!socketPath || !auth) return fail();
      const socket = net.createConnection(socketPath);
      socket.setEncoding('utf8');
      let output = '';
      let bytes = 0;
      let settled = false;
      const settleError = () => {
        if (settled) return;
        settled = true;
        fail();
      };
      const abort = () => socket.destroy(new Error('Controller request cancelled'));
      if (signal?.aborted) abort();
      else signal?.addEventListener('abort', abort, {once: true});
      socket.setTimeout(31 * 60 * 1000, abort);
      socket.on('connect', () => socket.write(JSON.stringify({...value, auth}) + '\n'));
      socket.on('data', (chunk) => {
        bytes += Buffer.byteLength(chunk);
        if (bytes > 2 * 1024 * 1024) return abort();
        output += chunk;
        let boundary;
        while ((boundary = output.indexOf('\n')) >= 0) {
          const line = output.slice(0, boundary);
          output = output.slice(boundary + 1);
          let frame;
          try { frame = JSON.parse(line); }
          catch { return settleError(); }
          if (frame?.status === 'progress') {
            if (frame.progress && onUpdate) {
              const progress = frame.progress;
              const text = progress.phase === 'scored'
                ? `Challenge ${progress.completed}/${progress.total}: ${progress.passed ? 'passed' : 'not passed'}.`
                : `Working on challenge ${Number(progress.completed ?? 0) + 1}/${progress.total}.`;
              try { onUpdate({content:[{type:'text',text}], details:{progress}}); }
              catch { /* Progress display cannot own or cancel host work. */ }
            }
            continue;
          }
          if (settled) return;
          settled = true;
          resolve(frame);
          socket.end();
          return;
        }
      });
      socket.on('error', settleError);
      socket.on('close', () => {
        signal?.removeEventListener('abort', abort);
        if (!settled) settleError();
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
    async execute(callId, kind, params, signal, onUpdate) {
      const binding = bindings.get(callId);
      bindings.delete(callId);
      if (!binding || binding.kind !== kind || turns.get(binding.runId) !== binding.token)
        throw new Error('Controller tool call has no current host admission.');
      const value = await request({op:'tool', run_id:binding.runId, turn_token:binding.token,
        call_id:callId, kind, params}, signal, onUpdate);
      if (value.status === 'busy') return {status:'busy', message:'Host workload needs attention',
        recovery_required:value.recovery_required === true};
      if (value.status === 'running') return value;
      if (value.status !== 'completed') throw new Error('Host controller tool did not complete.');
      return value.value;
    }
  };
}
