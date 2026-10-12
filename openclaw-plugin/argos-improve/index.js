import { spawn } from "node:child_process";
import { Type } from "typebox";

const TOOL_TIMEOUT_MS = 30 * 60 * 1000;
const MAX_OUTPUT = 2 * 1024 * 1024;
const ARGOS_BIN = process.env.ARGOS_BIN || "argos";

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
      if (code !== 0) return reject(new Error("Benchmark did not complete; inspect the local Argos status."));
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
    description: "Run the fixed Argos ability suite through the configured OpenClaw main assistant. Saves a private scored run; does not change configuration.",
    parameters: Type.Object({
      suite: Type.Optional(Type.Union([Type.Literal("quick"), Type.Literal("standard")],
        { description: "Quick 20-task suite or full 70-task suite." }))
    }, { additionalProperties: false }),
    async execute(_id, params, signal, onUpdate) {
      const value = await runArgos("openclaw",
        ["--suite", params.suite ?? "quick", "--json"], signal, onUpdate);
      const run = value.result;
      const summary = run?.summary;
      if (!run || !summary || !run.coverage) throw new Error("Benchmark result is incomplete.");
      const progress = `${run.coverage.completed}/${run.coverage.total} tasks`;
      const outcome = run.state === "completed"
        ? `${summary.correct}/${summary.total} passed`
        : `stopped after ${progress} (${run.failure_code ?? run.state}); this partial run cannot be compared`;
      const text = `OpenClaw benchmark ${outcome}. Run ID: ${run.id}. Suite: ${run.suite_version}. Complete coverage: ${run.coverage.complete ? "yes" : "no"}. Saved privately at ${value.path}.`;
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
      const promptNote = result.workspace_agents_changed
        ? "Workspace instructions differ between runs; treat this as an experiment, not identical setup."
        : "Workspace instruction fingerprint is unchanged between runs.";
      return textResult(`${promptNote}\n${JSON.stringify(result, null, 2)}`, { comparison: result });
    }
  });
}
