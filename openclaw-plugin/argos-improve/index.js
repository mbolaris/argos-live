import { spawn } from "node:child_process";
import { Type } from "typebox";

const TOOL_TIMEOUT_MS = 30 * 60 * 1000;
const MAX_OUTPUT = 2 * 1024 * 1024;
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
    const child = spawn(ARGOS_BIN, [...argosPrefixArgs(), "bench", command, ...args],
      { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, PYTHONUTF8: "1" } });
    let stdout = "";
    let stderr = "";
    let progressBuffer = "";
    let size = 0;
    const timer = setTimeout(() => child.kill("SIGTERM"), TOOL_TIMEOUT_MS);
    const abort = () => child.kill("SIGTERM");
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      size += Buffer.byteLength(chunk);
      if (size > MAX_OUTPUT) child.kill("SIGTERM");
      else stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      progressBuffer += chunk;
      const lines = progressBuffer.split(/\r?\n/);
      progressBuffer = lines.pop() ?? "";
      for (const line of lines) {
        try {
          const event = JSON.parse(line);
          const text = event.phase === "scored"
            ? `Challenge ${event.completed}/${event.total}: ${event.receipt?.score ? "passed" : "not passed"}. ${event.receipt?.output ?? ""}`
            : `Working on challenge ${event.completed + 1}/${event.total}.`;
          onUpdate?.({ content: [{ type: "text", text }], details: { progress: event } });
        } catch { if (Buffer.byteLength(stderr) < 32768) stderr += line; }
      }
    });
    child.on("error", () => { clearTimeout(timer); signal?.removeEventListener("abort", abort); reject(new Error("Argos benchmark command is unavailable.")); });
    child.on("close", (code) => {
      clearTimeout(timer);
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
  api.registerTool({
    name: "argos_evaluate",
    label: "Evaluate OpenClaw",
    description: "Measure fixed text tasks with copies of your current instructions in isolated, tool-free OpenClaw state. Save a scored run. Run evaluations sequentially; repeat a candidate to confirm a gain before making another change. Does not change owner configuration.",
    parameters: Type.Object({
      suite: Type.Optional(Type.Union([Type.Literal("quick"), Type.Literal("standard")],
        { description: "Quick 20-task suite or full 70-task suite." }))
    }, { additionalProperties: false }),
    async execute(_id, params, signal, onUpdate) {
      const value = await runArgos("openclaw",
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
      const result = await runArgos("results", ["--compare", params.baseline_id,
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
      const value = await runArgos("log", ["--text", params.text, "--json"], signal);
      return textResult(value.status === "busy" ? `${value.message}. No note appended.` :
        `Appended at host time ${value.observed}. Pre-append snapshot: ${value.snapshot}.`, value);
    }
  });
}
