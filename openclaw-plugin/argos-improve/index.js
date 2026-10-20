import { spawn } from "node:child_process";
import { Type } from "typebox";
import { registerAdmission } from "./admission.js";

const TOOL_TIMEOUT_MS = 30 * 60 * 1000;
const TERMINATION_GRACE_MS = 5 * 1000;
const MAX_OUTPUT = 2 * 1024 * 1024;
const MAX_PROGRESS_LINE = 65536;
const ARGOS_BIN = process.env.ARGOS_BIN || "argos";
const EVALUATION_PATH = "openclaw embedded; ephemeral state; tools denied; v2";

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

export default function register(api) {
  const admission = registerAdmission(api);
  const savedId = () => Type.String({minLength:32,maxLength:32,pattern:'^[a-f0-9]{32}$'});
  const hash = () => Type.String({minLength:64,maxLength:64,pattern:'^[a-f0-9]{64}$'});
  const controlled = async (id, kind, params, signal, onUpdate) => {
    if (!admission) throw new Error('This tool requires a managed host controller.');
    const value = await admission.execute(id, kind, params, signal, onUpdate);
    return textResult(JSON.stringify(value, null, 2), value);
  };
  api.registerTool({
    name:'argos_inspect', label:'Inspect current experiment setup',
    description:'Read your current AGENTS.md, its hash, safe configured generation settings, pending change and keep evidence policy. No arbitrary file paths or credentials.',
    parameters:Type.Object({}, {additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'inspect',params,signal); }
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
    description:'Start only the exam preselected by the host. You cannot choose its form, exposure tier, model identity or assistance policy. The service withholds scores, answer keys and signed transcripts from these tools.',
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
    description:'Read one question from the currently active module. The host owns the cartridge and the service never returns the answer key or routing rules.',
    parameters:Type.Object({item_id:Type.String({minLength:1,maxLength:96})},{additionalProperties:false}),
    async execute(id, params, signal) { return controlled(id,'proctor_item',params,signal); }
  }, {optional:true});
  api.registerTool({
    name:'argos_proctor_answer', label:'Submit an exam answer',
    description:'Submit an answer for an item in the active module. The service assigns the revision and records the attempt; you cannot set exam conditions or revisions.',
    parameters:Type.Object({item_id:Type.String({minLength:1,maxLength:96}),answer:Type.String({maxLength:8192})},{additionalProperties:false}),
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
    name: "argos_evaluate",
    label: "Evaluate OpenClaw",
    description: "Measure fixed text tasks with copies of your current instructions in isolated, tool-free OpenClaw state. Save a scored run. Run evaluations sequentially; repeat a candidate to confirm a gain before making another change. Does not change owner configuration.",
    parameters: Type.Object({
      suite: Type.Optional(Type.Union([Type.Literal("quick"), Type.Literal("standard"), Type.Literal("challenge")],
        { description: "Quick 20-task suite, standard 70-task suite, or separate 40-task challenge form." }))
    }, { additionalProperties: false }),
    async execute(_id, params, signal, onUpdate) {
      const value = admission ? await admission.execute(_id, 'evaluation',
        {suite:params.suite ?? 'quick'}, signal, onUpdate) : await runArgos("openclaw",
        ["--suite", params.suite ?? "quick", "--json"], signal, onUpdate);
      if (value.status === "busy") return textResult(
        `${value.message}. No evaluation started. Wait for the active workload; do not edit the workspace.`, value);
      const run = value.result;
      const summary = run?.summary;
      if (!run || !summary || !run.coverage) throw new Error("Benchmark result is incomplete.");
      if (run.suite !== `openclaw-${params.suite ?? "quick"}` ||
          !run.suite_version?.startsWith("argos-openclaw-ability/") ||
          run.settings?.execution_path !== EVALUATION_PATH) {
        throw new Error("Expected an OpenClaw assistant benchmark. Raw model runs do not test assistant instructions.");
      }
      const progress = `${run.coverage.completed}/${run.coverage.total} tasks`;
      const outcome = run.state === "completed"
        ? `${summary.correct}/${summary.total} passed`
        : `stopped after ${progress} (${run.failure_code ?? run.state}); this partial run cannot be compared`;
      const next = run.state === "completed"
        ? "Next: append the saved run ID and score to IMPROVEMENT-LOG.md. Compare matched runs and repeat a candidate to confirm a gain. Change only one thing between experiments; do not change setup during a run."
        : "Next: note the failure in IMPROVEMENT-LOG.md and fix its cause before retesting.";
      const text = `OpenClaw benchmark ${outcome}. Run ID: ${run.id}. Suite: ${run.suite_version}. Complete coverage: ${run.coverage.complete ? "yes" : "no"}. Saved privately at ${value.path}. ${next}`;
      return textResult(text, { run_id: run.id, suite_version: run.suite_version,
        suite_sha256: run.settings?.suite_sha256,
        prompt_fingerprint: run.prompt_fingerprint,
        state: run.state, summary, coverage: run.coverage, elapsed_seconds: run.elapsed_seconds });
    }
  });
  api.registerTool({
    name: "argos_compare",
    label: "Compare OpenClaw runs",
    description: "Compare two compatible saved Argos benchmark runs with the deterministic scorer.",
    parameters: Type.Object({
      baseline_id: Type.String({ minLength: 32, maxLength: 32, pattern: "^[a-f0-9]{32}$" }),
      candidate_id: Type.String({ minLength: 32, maxLength: 32, pattern: "^[a-f0-9]{32}$" })
    }, { additionalProperties: false }),
    async execute(_id, params) {
      const result = admission ? await admission.execute(_id, 'compare', params) :
        await runArgos("results", ["--compare", params.baseline_id,
        params.candidate_id, "--json"]);
      if (result.kind !== "ability" || !result.suite_version?.startsWith("argos-openclaw-ability/") ||
          result.settings?.execution_path !== EVALUATION_PATH) {
        throw new Error("Expected an OpenClaw assistant comparison. Raw model runs do not test assistant instructions.");
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
      return textResult(value.status === "busy" ? `${value.message}. No note appended.` :
        `Appended at host time ${value.observed}. Pre-append snapshot: ${value.snapshot}.`, value);
    }
  });
}
