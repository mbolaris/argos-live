# Original ability suites and deterministic scoring

B4a ships original MIT-licensed `quick` (20 items), `standard` (70 items),
`challenge` (40 items), `tool-schema` (40 items), `tool-plan` (40 items) and
`tool-sequence` (40 items)
fixtures at `argoslive/data/ability/`. Quick and standard are version 1.0.0;
challenge is version 1.2.0; tool-schema is version 1.2.0; tool-plan is version
1.1.0; tool-sequence is version 1.0.0. Challenge 1.0.0, challenge 1.1.0 and tool-plan 1.0.0
are retained for historical result replay. Tool-plan 1.1.0 makes exact order and
reviewer-role string values explicit in the supplied schemas; 1.0.0 used only
primitive `string` types while scoring exact hidden literals. Establish a fresh
1.1.0 baseline and never compare it with 1.0.0.
Challenge 1.2.0 specifies the lowercase `json` format argument in action-03,
which 1.1.0 left ambiguous. Establish a fresh 1.2.0 baseline; scores across
the two versions are not a matched comparison.
Quick contains four items from each of five categories; standard contains
fourteen per category and includes quick as an exact subset. Challenge is a
separately authored form with eight items per category and multi-step numeric,
constraint-selection, structured extraction and inert action-format prompts.
Challenge is a distinct form, not a held-out external benchmark. Challenge
1.0.0's eight tool-call prompts do not supply an available-tool inventory or
schemas. Historical scores remain visible, but that category cannot justify a
tool-use diagnosis or qualify an instruction change under keep policy v3.
Challenge 1.1.0 preserves the other tasks and adds four explicit, typed tool
schemas to each tool-call prompt, but action-03 does not specify the case of its
format argument. Keep policy v3 excludes its tool-call category from
qualification; existing v2 journals retain their original policy. Use challenge
1.2.0, tool-schema, or tool-plan for tool-call experiments. Tool-schema
contains only inert proposed tool calls: every prompt supplies three available
tool schemas with descriptions and typed arguments; 20 practice and 20 held-out
items use disjoint tool names and argument keys. Correct tools appear in all
three list positions, balanced 6/7/7 per partition, so always choosing the first
entry cannot pass. Held-out means held out from the practice vocabulary, not an
external benchmark. Tool-plan has 20 practice and 20 bundled held-out items; it
uses four candidate tools and asks for multi-constraint selection, small value
derivations and complete argument assembly. Each tool appears as the target five
times in each partition, with target position balanced across all four slots.
Its held-out vocabulary is an internal transfer check, not independent
validation. These remain Argos probes,
not GSM8K, MMLU, a comprehensive intelligence evaluation or real tool
acceptance.

Tool-schema 1.2.0 states the exact JSON call shape (`name` and `arguments`),
rejects the common `tool` alias, and forbids Markdown fences. Its scores are a
new baseline and must not be compared with 1.1.0.

`scripts/build-original-ability-suites.py` reproduces all checked-in fixtures
without downloads. Every item has an original prompt, stable ID, deterministic
scoring rule, passing reference, semantically wrong answer and malformed answer.
The packaged NOTICE includes provenance, limits and the MIT license. The normal
runtime package installer includes all six suites and the notice in the image.
Changes to prompts, expected answers or scoring semantics require a suite version
change; later results comparison must refuse mixed versions.

`ability.load()` validates metadata and all fixtures. `ability.score()` returns
`pass`, `wrong_answer` or `format_error`, plus a binary score and format validity.
No LLM judges are used. Numeric answers accept a single decimal/scientific value,
grouped thousands, common answer prefixes and trailing punctuation. Additional
numbers or explanatory prose fail the explicit one-number contract. Choice
answers accept one A–D letter with simple label/parenthesis punctuation. Code
fences around a complete text/JSON answer are tolerated.

Instruction checks count words using the versioned Python word-token regex,
check whole-word keywords case-insensitively, enforce word limits, single lines
and optional uppercase. A nonempty answer violating a constraint is wrong; an
empty/non-text answer is malformed. JSON uses a deliberately restricted closed
reference-derived schema: exact object keys, tuple lengths and primitive types;
integers use JSON integer representation, not floats or booleans. Duplicate
keys, nonfinite numbers, extra fields and incorrect types fail format. Correct
shape with incorrect values is wrong. This is not a general JSON Schema engine.

Tool-format items require exactly `name` and an `arguments` object. Tool-sequence
items require a `steps` array of two or three schema-valid calls and explicit
literal references to fields returned by earlier steps. They assess planning
and reference handling only; calls are never executed. Tool-sequence has 20
practice and 20 bundled held-out workflows with disjoint tool names and argument
keys; held-out scores are an internal transfer signal, not independent
validation. Tool-format items assess specified argument values only. They never
register, grant or invoke tools. `tool_execution_verified` stays false even for
a passing answer. No
generated code is executed. Output is bounded to 64 KiB UTF-8; malformed Unicode
and excessively nested JSON fail without evaluation or shell calls.

B4b retains code tasks and an actual enforced no-network/filesystem sandbox.
A temporary directory and timeout alone do not enforce those boundaries.

## Running the probes

`argos bench ability --model qwen3:0.6b --suite quick` runs without setup against
an already-installed exact Ollama tag. Standard selects 70 items. Stop competing
assistant workloads first. The model must advertise at least 2048 context tokens.
Generation uses context 2048, seed 1, temperature 0 and a 128-token limit; thinking
is disabled only when the model advertises that capability. Deterministic settings
do not guarantee identical output across hardware or upstream runtime revisions.

Each item saves raw output bounded to 8 KiB UTF-8 (with a truncation flag), score, format outcome, measured latency,
backend placement and reported token/timing fields. Progress reports completed
items, elapsed time and ETA from measured completed-item time; no ETA appears
before the first item completes. No answer is retried or judged by another model.
The first item includes loading time; this is an ability run, not a speed ranking.

The runner unloads the candidate in a finally block and reloads the previously
loaded model with its reported context. More than one loaded model is refused.
Other previous runner options cannot be recovered from `/api/ps`; restoration
does not restore unreported settings. Ctrl+C or cancellation saves partial evidence
with `state: cancelled`, incomplete coverage, and exit status 130. Backend or
restoration errors fail the run and do not save a successful result.

Private JSON files go to `~/.local/share/argos-live/results/`. `--json` emits the
result without progress text; `--results-dir`, `--ollama` and a bounded `--timeout`
are available. Every form has its own version identity; comparisons reject mixed
forms. Code execution remains explicitly omitted, and partial runs must not rank
beside complete ones.
B6 adds result management/comparison; B7 adds combined speed/ability CLI runs.
Real CPU integration checks completion and restoration, not a minimum model score
or the GPU timing target. Physical Live/GPU acceptance remains separate.
