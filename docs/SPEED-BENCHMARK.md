# Speed benchmark

`argos bench speed --model qwen3:0.6b [--json] [--ollama http://127.0.0.1:11434]`
benchmarks an already-installed exact tag without setup or downloads. Add `--size short` for the quick onboarding run, or repeat `--size` to select cases; the default runs all three sizes. Selected sizes are recorded in settings and must match when comparing results. Stop other
assistant workloads before benchmarking. The command does not stop or detect
unrelated services. It refuses to begin if more than one model is already loaded.

Results are private `argos-bench/1` JSON files in
`~/.local/share/argos-live/results/`; `--results-dir` can select an existing private
directory. Use encrypted persistence for retained personal results. The runner
uses public fixed text and never owner conversation prompts. It does not modify
agent selection, provider settings or model files. Results comparison/storage
management belongs to B6.

The `speed/1` prompts have nominal sizes about 128, 2k and 8k input tokens;
token counts are measured by Ollama rather than inferred from their characters.
Requested contexts are 2048, 4096 and 12288 to leave headroom for the prompt and
128-token generation limit. Unknown/smaller advertised context skips that case
with a reason. The long prompt is not forced into a small model context.

Each size has one warm-up and three measured requests. Temperature is zero and
seed one. Thinking is disabled when the backend advertises that capability.
Generation is limited to 128 tokens, not padded to 128 if the model ends earlier.
Warm-ups are stored separately and excluded from medians/ranges. The first
warm-up follows explicit unload and is additionally recorded as the cold load
sample; operating-system filesystem caches are not cleared.

Prompt processing and generation tokens/second use reported counts divided by
reported nanosecond durations. Stream time to first token is measured by B2.
Missing fields, zero-duration rates and non-finite metrics remain null. Summaries
include reported sample counts, so a median based on fewer than three usable
measurements is visible. Token rates across tokenizers are descriptive rather
than equivalent-work scores.

The record contains UTC/run ID, schema/suite/version, exact API-reported model
digest, model metadata, Ollama/Argos versions, hardware snapshot, settings,
per-run raw timings/counts, prompt summaries and restoration evidence. CPU/GPU/
split placement is derived conservatively from each API ps snapshot; absent or
inconsistent memory fields leave it unknown. Layer counts stay null because ps
does not reliably expose them. Hardware snapshots do not claim peak RAM/VRAM.

The previously loaded model is unloaded before measurement, then the candidate
is unloaded in a finally block. A previous model is reloaded through an empty
prompt with its reported context, including when benchmarking fails. Other
previous generation options and remaining keep-alive time are not reconstructed;
reload uses five minutes. Restoration failure raises an error rather than
reporting success. No model was previously loaded means the candidate is simply
unloaded afterward. This is not a whole-service settings snapshot.

Fixture tests cover cold/warm separation, median/range, skips, missing metrics,
placement, refusal with multiple loaded models, restoration on interruption and
CLI JSON output. The separately labeled network smoke uses checksum-pinned
Ollama 0.35.0/qwen3:0.6b on a Linux CPU runner, saves a result, checks model/context
restoration and gates the short onboarding benchmark at under 60 seconds. The complete short/medium/long run is tested separately without that quick-run time target. Benchmark API reads have a bounded 120-second timeout for slow CPU prefill. Actual Live
desktop/GPU performance cards and physical comparisons remain unverified.

