import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { Type } from "typebox";
import { registerAdmission } from "./admission.js";

const TOOL_TIMEOUT_MS = 30 * 60 * 1000;
const TERMINATION_GRACE_MS = 5 * 1000;
const MAX_OUTPUT = 2 * 1024 * 1024;
const MAX_PROGRESS_LINE = 65536;
const ARGOS_BIN = process.env.ARGOS_BIN || "argos";
const EVALUATION_PATH = "openclaw embedded; ephemeral state; tools denied; v2";
const EVALUATION_WAIT_MS = 8 * 60 * 1000;
const directEvaluationJobs = new Map();

function argosPrefixArgs() {
  if (!process.env.ARGOS_BIN_ARGS) return [];
  let value;
  try { value = JSON.parse(process.env.ARGOS_BIN_ARGS); }
  catch { throw new Error("Argos command wrapper arguments must be a JSON string array."); }
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string"))
    throw new Error("Argos command wrapper arguments must be a JSON string array.");
  return value;
}

function runArgos(command, args, signal, onUpdate) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error("Argos request was cancelled before dispatch; no command started."));
      return;
    }
    const child = spawn(ARGOS_BIN, [...argosPrefixArgs(), "bench", command, ...args],
      { stdio: ["ignore", "pipe", "pipe"], detached: process.platform !== "win32",
        env: { ...process.env, PYTHONUTF8: "1" } });
    let stdout = "";
    let stderr = "";
    let progressBuffer = "";
    let discardProgressLine = false;
    let size = 0;
    let terminationTimer;
    let terminationRequested = false;
    let closed = false;
    const signalChild = (signalName) => {
      if (process.platform !== "win32" && child.pid) {
        try {
          process.kill(-child.pid, signalName);
          return;
        } catch { /* Fall back to the direct child when its process group is unavailable. */ }
      }
      child.kill(signalName);
    };
    const terminate = () => {
      if (terminationRequested || closed) return;
      terminationRequested = true;
      signalChild("SIGTERM");
      terminationTimer = setTimeout(() => {
        if (!closed) signalChild("SIGKILL");
      }, TERMINATION_GRACE_MS);
      terminationTimer.unref?.();
    };
    const timer = setTimeout(terminate, TOOL_TIMEOUT_MS);
    const abort = () => terminate();
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      size += Buffer.byteLength(chunk);
      if (size > MAX_OUTPUT) terminate();
      else stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      if (discardProgressLine) {
        const boundary = chunk.indexOf("\n");
        if (boundary < 0) return;
        chunk = chunk.slice(boundary + 1);
        discardProgressLine = false;
      }
      progressBuffer += chunk;
      const lines = progressBuffer.split(/\r?\n/);
      progressBuffer = lines.pop() ?? "";
      if (Buffer.byteLength(progressBuffer) > MAX_PROGRESS_LINE) {
        progressBuffer = "";
        discardProgressLine = true;
      }
      for (const line of lines) {
        if (Buffer.byteLength(line) > MAX_PROGRESS_LINE) continue;
        try {
          const event = JSON.parse(line);
          if (!event || !["asking", "scored"].includes(event.phase) ||
              !Number.isInteger(event.completed) || !Number.isInteger(event.total) ||
              ![20, 40, 70].includes(event.total) || event.completed < 0 ||
              event.completed > event.total ||
              (event.phase === "asking" && event.completed === event.total)) continue;
          const text = event.phase === "scored"
            ? `Challenge ${event.completed}/${event.total}: ${event.receipt?.score ? "passed" : "not passed"}. ${event.receipt?.output ?? ""}`
            : `Working on challenge ${event.completed + 1}/${event.total}.`;
          onUpdate?.({ content: [{ type: "text", text }], details: { progress: event } });
        } catch { if (Buffer.byteLength(stderr) < 32768) stderr += line; }
      }
    });
    child.on("error", () => {
      clearTimeout(timer);
      clearTimeout(terminationTimer);
      signal?.removeEventListener("abort", abort);
      reject(new Error("Argos benchmark command is unavailable."));
    });
    child.on("close", (code) => {
      closed = true;
      clearTimeout(timer);
      clearTimeout(terminationTimer);
      signal?.removeEventListener("abort", abort);
      if (code !== 0) {
        if (code === 75) {
          try {
            const busy = JSON.parse(stdout);
            if (busy.status === "busy") return resolve(busy);
          } catch { /* Invalid data is still a failed command. */ }
        }
        return reject(new Error("Argos command did not complete; inspect the local Argos status."));
      }
      try { resolve(JSON.parse(stdout)); }
      catch { reject(new Error("Benchmark returned invalid result data.")); }
    });
  });
}

function textResult(text, details) {
  return { content: [{ type: "text", text }], details };
}

function renderEvaluation(value) {
  const run = value?.result;
  const summary = run?.summary;
  if (!run || !summary || !run.coverage) throw new Error("Benchmark result is incomplete.");
  if (!run.suite?.startsWith("openclaw-") ||
      !run.suite_version?.startsWith("argos-openclaw-ability/") ||
      run.settings?.execution_path !== EVALUATION_PATH) {
    throw new Error("Expected an OpenClaw assistant benchmark. Raw model runs do not test assistant instructions.");
  }
  const progress = `${run.coverage.completed}/${run.coverage.total} tasks`;
  const outcome = run.state === "completed"
    ? `${summary.correct}/${summary.total} passed`
    : `stopped after ${progress} (${run.failure_code ?? run.state}); this partial run cannot be compared`;
  const partitionLabel = run.suite === "openclaw-tool-sequence" ? "held-out workflows" : "unseen-vocabulary";
  const partitions = summary.partitions
    ? ` Practice: ${summary.partitions.practice?.correct ?? 0}/20; ${partitionLabel}: ${summary.partitions.heldout?.correct ?? 0}/20 (same bundled suite, not independent validation).`
    : "";
  const next = run.state === "completed"
    ? "Next: append the saved run ID and score to IMPROVEMENT-LOG.md. Compare matched runs and repeat a candidate to confirm a gain. Change only one thing between experiments; do not change setup during a run."
    : "Next: note the failure in IMPROVEMENT-LOG.md and fix its cause before retesting.";
  const text = `OpenClaw benchmark ${outcome}.${partitions} Run ID: ${run.id}. Suite: ${run.suite_version}. Complete coverage: ${run.coverage.complete ? "yes" : "no"}. Saved privately at ${value.path}. ${next}`;
  return textResult(text, {run_id:run.id, suite_version:run.suite_version,
    suite_sha256:run.settings?.suite_sha256, prompt_fingerprint:run.prompt_fingerprint,
    state:run.state, summary, coverage:run.coverage, elapsed_seconds:run.elapsed_seconds});
}

function evaluationProgress(job, callback, event) {
  job.progress = {completed:event.completed, total:event.total};
  try { callback?.(event); } catch { /* Losing a progress consumer never cancels the host job. */ }
}

async function waitForDirectEvaluation(job, signal, onUpdate) {
  if (!job?.completion || !job.id) throw new Error("Unknown evaluation job ID.");
  job.onUpdate = onUpdate;
  if (signal?.aborted) return {status:"running", job_id:job.id, suite:job.suite, ...job.progress};
  let timer;
  const timeout = new Promise((resolve) => { timer = setTimeout(() => resolve(null), EVALUATION_WAIT_MS); });
  let abortHandler;
  const aborted = signal ? new Promise((resolve) => {
    abortHandler = () => resolve(null);
    signal.addEventListener("abort", abortHandler, {once:true});
  }) : new Promise(() => {});
  const result = await Promise.race([job.completion, timeout, aborted]);
  clearTimeout(timer);
  if (abortHandler) signal.removeEventListener("abort", abortHandler);
  job.onUpdate = null;
  if (result) {
    directEvaluationJobs.delete(job.id);
    return result;
  }
  return {status:"running", job_id:job.id, suite:job.suite, ...job.progress};
}

function startDirectEvaluation(suite, signal, onUpdate) {
  if (signal?.aborted) throw new Error("Argos request was cancelled before dispatch; no command started.");
  const id = randomBytes(16).toString("hex");
  const job = {id, suite, progress:{completed:0,total:suite === "challenge" || suite === "tool-schema" || suite === "tool-plan" || suite === "tool-sequence" ? 40 : suite === "standard" ? 70 : 20}};
  job.ownerCancellation = new AbortController();
  job.cancel = () => job.ownerCancellation.abort();
  job.completion = runArgos("openclaw", ["--suite", suite, "--json"], job.ownerCancellation.signal,
    (event) => evaluationProgress(job, job.onUpdate, event)).then((value) => {
      job.finished = true;
      return {status:"completed", value};
    }, () => {
      job.finished = true;
      return {status:"failed", error:"Argos evaluation did not complete; inspect the local Argos status."};
    });
  directEvaluationJobs.set(id, job);
  return waitForDirectEvaluation(job, signal, onUpdate).then((value) => {
    if (value.status === "completed") return value.value;
    if (value.status === "failed") throw new Error(value.error);
    return value;
  });
}

// Called only by the trusted host owner-control adapter; this is not registered
// as an agent tool. Aborting an agent's wait signal never invokes this method.
export function cancelDirectEvaluation(jobId) {
  const job = directEvaluationJobs.get(jobId);
  if (!job) throw new Error("Unknown evaluation job ID.");
  if (job.finished) return {status:"already_finished", job_id:jobId};
  job.cancel();
  return {status:"cancel_requested", job_id:jobId};
}

export default function register(api) {
  const admission = registerAdmission(api);
  const savedId = () => Type.String({minLength:32,maxLength:32,pattern:'^[a-f0-9]{32}$'});
  const hash = () => Type.String({minLength:64,maxLength:64,pattern:'^[a-f0-9]{64}$'});
  const controlled = async (id, kind, params, signal, onUpdate) => {
    if (!admission) throw new Error('This tool requires a managed host controller.');
    const value = await admission.execute(id, kind, params, signal, onUpdate);
    let instruction = '';
    if (kind.startsWith('proctor_') && value.status !== 'busy') {
      if (value.next_step?.tool && value.next_step?.arguments) {
        instruction = value.next_step.instruction ? value.next_step.instruction + ' Then '
          : value.state === 'COMPLETED'
          ? 'The exam is complete. Request the permitted practice feedback now. '
          : 'The exam is not finished. Continue now; do not end your turn. ';
        instruction += `Call ${value.next_step.tool} with ${JSON.stringify(value.next_step.arguments)}.`;
      } else if (kind === 'proctor_item' && typeof value.item_id === 'string') {
        if (value.domain === 'tool_call_format') {
          instruction = `Follow the tool-call task yourself. Make the requested argos_evaluate_wait tool call; the host records that actual call as your answer. This is a Proctor simulation and starts no evaluation. Do not submit JSON through argos_proctor_answer. Do not end your turn.`;
        } else {
          const format = value.response_type === 'mcq_single' ? 'Use one choice key, not the choice text.' :
            value.response_type === 'numeric_grid' ? 'Use only the number, with no units or explanation.' :
              'Return one JSON object matching the supplied schema.';
          instruction = `Solve the question below yourself. Your next action must call argos_proctor_answer with item_id ${JSON.stringify(value.item_id)} and your answer as a string. ${format} Do not end your turn.`;
        }
      }
    }
    return textResult((instruction ? instruction + '\n\n' : '') + JSON.stringify(value, null, 2), value);
  };
  api.registerTool({
    name:'argos_inspect', label:'Inspect current experiment setup',
    description:'Read your current AGENTS.md, its hash, safe configured generation settings, pending change and keep evidence policy. No arbitrary file paths or credentials.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'inspect',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_audit_instructions', label:'Audit saved instruction experiments',
    description:'Verify the host-managed instruction journal, snapshots, matched saved-run receipts, and keep/restore decisions. Returns run IDs and aggregate scores without answers. An empty journal is valid; this does not verify free-form log claims or independent transfer.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'audit',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_edit_instructions', label:'Try one instruction change',
    description:'Apply one unique literal replacement in AGENTS.md after a host snapshot. Choose your own hypothesis and patch. Requires the current hash and a saved matching baseline from this controller. Resolve this change before another edit.',
    parameters:Type.Object({baseline_id:savedId(),expected_sha256:hash(),
      find:Type.String({minLength:1,maxLength:4096}), replace:Type.String({maxLength:4096}),
      hypothesis:Type.String({minLength:1,maxLength:1024})}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'edit',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_resolve_instructions', label:'Keep or restore your instruction change',
    description:'Choose keep or restore for your pending instruction experiment. Keep needs at least two matched baseline and two fresh candidate runs meeting the host practice policy. Restore checks snapshot bytes and preserves other configuration; without valid candidate IDs it does not count as a measured experiment. This does not certify independent gain.',
    parameters:Type.Object({change_id:savedId(),expected_sha256:hash(),
      action:Type.Union([Type.Literal('keep'),Type.Literal('restore')]),
      baseline_ids:Type.Optional(Type.Array(savedId(),{minItems:1,maxItems:8})),
      candidate_ids:Type.Optional(Type.Array(savedId(),{minItems:1,maxItems:8}))}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'resolve',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_start', label:'Start the host-selected ability exam',
    description:'Start only the exam preselected by the host, then call the tool in next_step with its arguments. Starting does not complete the exam. You cannot choose its form, exposure tier, model identity or assistance policy. Scores and answer keys are withheld until terminal practice feedback.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_start',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_status', label:'Check current exam status',
    description:'Check the active host-selected Proctor session, remaining time and current module state. This does not reveal answers or scores.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_status',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_item', label:'Get an active exam question',
    description:'Read one question from the currently active module, solve it yourself, then call argos_proctor_answer with this item_id and your answer as a string. The host binds answers to retrieved active items. The service never returns the answer key or routing rules.',
    parameters:Type.Object({item_id:Type.String({minLength:1,maxLength:96})},{additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_item',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_answer', label:'Submit an exam answer',
    description:'Record your own answer for a question surfaced by the host or returned by argos_proctor_item. Include that active item_id and answer as strings. The host rejects unseen, inactive, and cross-module items. Accepted means recorded, not correct. The service assigns the revision; you cannot set exam conditions or revisions.',
    parameters:Type.Object({item_id:Type.String({minLength:1,maxLength:96}),
      answer:Type.String({maxLength:8192})},{additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_answer',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_continue', label:'Continue to the next exam module',
    description:'Begin the next server-selected module when its recorded break permits. You cannot choose or skip modules.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_continue',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_submit', label:'Submit the current exam module',
    description:'Submit the module ID reported by the current Proctor status. The service verifies it is still active and withholds correctness, total scores and signed transcripts from the examinee tools.',
    parameters:Type.Object({module_id:Type.String({minLength:1,maxLength:96})},{additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_submit',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_feedback', label:'Review practice exam feedback',
    description:'Review aggregate score and domain counts only for a host-selected practice session after it ends. Assessment and held-out sessions never return feedback to the examinee.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_feedback',params,signal); }
  }, {optional:true});
  api.registerTool({
    name: "argos_evaluate",
    label: "Evaluate OpenClaw",
    description: "Measure fixed text tasks with copies of your current instructions in isolated, tool-free OpenClaw state. Save a scored run. Run evaluations sequentially; repeat a candidate to confirm a gain before making another change. Does not change owner configuration.",
    parameters: Type.Object({
      suite: Type.Optional(Type.Union([Type.Literal("quick"), Type.Literal("standard"), Type.Literal("challenge"), Type.Literal("tool-schema"), Type.Literal("tool-plan"), Type.Literal("tool-sequence")],
        { description: "Quick (20), standard (70), challenge (40), tool-schema (40 schema-grounded calls), tool-plan (40 multi-constraint calls), or tool-sequence (40 ordered two- and three-call plans with explicit prior-result references). Tool suites include bundled held-out items; these are internal transfer checks, not independent validation or real tool execution." }))
    }, { additionalProperties: false }),
    async execute(_id, params, signal, onUpdate) {
      const suite = params.suite ?? 'quick';
      const value = admission ? await admission.execute(_id, 'evaluation',
        {suite}, signal, onUpdate) : await startDirectEvaluation(suite, signal, onUpdate);
      if (value.status === "busy") return textResult(
        `${value.message}. No evaluation started. Wait for the active workload; do not edit the workspace.`, value);
      if (value.status === "running") return textResult(
        `Evaluation is still running (${value.completed}/${value.total}). Use argos_evaluate_wait with job ID ${value.job_id}; do not start another evaluation or edit the workspace.`, value);
      return renderEvaluation(value);
    }
  });
  api.registerTool({
    name:"argos_evaluate_wait", label:"Wait for an evaluation job",
    description:"Continue waiting for a host-owned evaluation. Each wait is bounded to eight minutes; if it is still running, use this tool again with the returned job ID. The original evaluation continues if your turn ends.",
    parameters:Type.Object({job_id:Type.String({minLength:32,maxLength:32,pattern:"^[a-f0-9]{32}$"})},{additionalProperties:false}),
    async execute(_id, params, signal, onUpdate) {
      const value = admission ? await admission.execute(_id, 'evaluation_wait', params, signal, onUpdate) :
        await waitForDirectEvaluation(directEvaluationJobs.get(params.job_id) ?? {}, signal, onUpdate);
      if (value.status === "running") return textResult(
        `Evaluation is still running (${value.completed}/${value.total}). Use argos_evaluate_wait again with job ID ${value.job_id}.`, value);
      if (value.status === "busy") return textResult("Host workload needs attention; do not start another evaluation.", value);
      if (!admission && value.status === "failed") throw new Error(value.error);
      const result = admission ? value : value.value;
      if (result?.status === "running") return textResult(
        `Evaluation is still running (${result.completed}/${result.total}). Use argos_evaluate_wait again with job ID ${result.job_id}.`, result);
      if (result?.status === "busy") return textResult("Host workload needs attention; do not start another evaluation.", result);
      if (result?.proctor_simulation === true) return textResult(result.message, result);
      return renderEvaluation(result);
    }
  }, {optional:true});
  api.registerTool({
    name:"argos_evaluate_status", label:"Find the current evaluation job",
    description:"Check whether a host-owned evaluation is still active and recover its job ID if your previous turn ended before receiving it. This never starts or cancels work.",
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(_id, _params) {
      let value;
      if (admission) value = await admission.execute(_id, 'evaluation_status', {});
      else {
        const job = [...directEvaluationJobs.values()].at(-1);
        value = !job ? {status:"idle"} : {status:job.finished ? "completed" : "running",
          job_id:job.id, suite:job.suite, ...job.progress};
      }
      if (value.status === "running") return textResult(
        `Evaluation is running (${value.completed}/${value.total}). Continue with argos_evaluate_wait and job ID ${value.job_id}.`, value);
      if (value.status === "completed") return textResult(
        `Evaluation finished and is saved. Retrieve its result with argos_evaluate_wait and job ID ${value.job_id}.`, value);
      if (value.status === "busy") return textResult("The evaluation workload needs host recovery; do not start another evaluation.", value);
      return textResult("No evaluation job is active.", value);
    }
  }, {optional:true});
  api.registerTool({
    name: "argos_compare",
    label: "Compare OpenClaw runs",
    description: "Compare two completed saved runs only when suite version, execution method, settings, recipe, and item coverage match. Different suites (for example quick and tool-plan) cannot be compared as before/after evidence. If runs are incompatible, the tool returns safe fingerprints, pair compatibility checks, and correction guidance.",
    parameters: Type.Object({
      baseline_id: Type.String({ minLength: 32, maxLength: 32, pattern: "^[a-f0-9]{32}$" }),
      candidate_id: Type.String({ minLength: 32, maxLength: 32, pattern: "^[a-f0-9]{32}$" })
    }, { additionalProperties: false }),
    async execute(_id, params) {
      const result = admission ? await admission.execute(_id, 'compare', params) :
        await runArgos("results", ["--compare", params.baseline_id,
        params.candidate_id, "--json"]);
      if (result?.status === "rejected") {
        const diagnostics = {runs:result.runs ?? [], pair_checks:result.pair_checks ?? null};
        return textResult(`${result.message}\nComparison diagnostics: ${JSON.stringify(diagnostics)}`, result);
      }
      if (result?.status === "busy") {
        const next = result.recovery_required
          ? "Host recovery is required before another comparison can run."
          : "Retry after the current host operation finishes.";
        return textResult(`${result.message || "Another host workload is active."} No comparison was run. ${next}`, result);
      }
      if (result.kind !== "ability" || !result.suite_version?.startsWith("argos-openclaw-ability/") ||
          result.settings?.execution_path !== EVALUATION_PATH) {
        return textResult("These runs are not from the configured OpenClaw assistant. Raw model benchmarks cannot measure changes to assistant instructions; choose saved IDs returned by argos_evaluate.",
          {status:"rejected", error_code:"not_openclaw_assistant"});
      }
      const promptNote = result.workspace_agents_changed
        ? "Workspace instructions differ between runs; treat this as an experiment, not identical setup."
        : "Workspace instruction fingerprint is unchanged between runs.";
      return textResult(`${promptNote}\n${JSON.stringify(result, null, 2)}`, { comparison: result });
    }
  });
  api.registerTool({
    name: "argos_log",
    label: "Append campaign log",
    description: "Append one short note to IMPROVEMENT-LOG.md with a host timestamp and checked receipts for referenced full saved run IDs. Include the complete ## Next or ## Done. Does not overwrite history. Notes about changes still require evidence; this tool does not verify prose claims.",
    parameters: Type.Object({ text: Type.String({ minLength: 1, maxLength: 4096 }) },
      { additionalProperties: false }),
    async execute(_id, params, signal) {
      const value = admission ? await admission.execute(_id, 'log', params, signal) :
        await runArgos("log", ["--text", params.text, "--json"], signal);
      if (value.status === "busy")
        return textResult(`${value.message || "Another host workload is active."}. No note appended.`, value);
      if (value.status === "failed")
        return textResult(`${value.message || "The campaign log operation failed."} The append outcome is unconfirmed; inspect IMPROVEMENT-LOG.md before retrying.`, value);
      if (value.status !== "appended")
        throw new Error("The campaign log did not confirm an append; inspect the local Argos status.");
      return textResult(`Appended at host time ${value.observed}. Pre-append snapshot: ${value.snapshot}.`, value);
    }
  });
}
