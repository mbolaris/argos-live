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
A temporary directory and timeout alone do not enforce those boundaries. B5
adds the Ollama runner and actual model smoke; B6 adds comparable results; B7
adds CLI commands. No model performance or physical acceptance is claimed by
fixture-only B4a scoring.
