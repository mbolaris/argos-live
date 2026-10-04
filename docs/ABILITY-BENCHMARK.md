# Original ability suites and deterministic scoring

B4a ships original MIT-licensed `quick` (20 items) and `standard` (70 items)
fixtures at `argoslive/data/ability/`, version 1.0.0. Quick contains four items
from each of five categories; standard contains fourteen per category. Quick is
an exact subset, not independent evidence. These are basic arithmetic,
knowledge-choice, instruction, JSON and inert tool-format probes, not GSM8K,
MMLU, a comprehensive intelligence evaluation or real tool acceptance.

`scripts/build-original-ability-suites.py` reproduces the checked-in fixtures
without downloads. Every item has an original prompt, stable ID, deterministic
scoring rule, passing reference, semantically wrong answer and malformed answer.
The packaged NOTICE includes provenance, limits and the MIT license. The normal
runtime package installer includes both suites and the notice in the image.
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

Tool-format items require exactly `name` and an `arguments` object. They assess
format and specified argument values only. They never register, grant or invoke
tools. `tool_execution_verified` stays false even for a passing answer. No
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

Each item saves bounded raw output, score, format outcome, measured latency,
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
are available. Quick and standard have distinct version identities. Code execution
remains explicitly omitted, and partial runs must not rank beside complete ones.
B6 adds result management/comparison; B7 adds combined speed/ability CLI runs.
Real CPU integration checks completion and restoration, not a minimum model score
or the GPU timing target. Physical Live/GPU acceptance remains separate.
