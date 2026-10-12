# Auto Climb watch and recovery findings

Observed on a physical persistent boot of the OpenClaw 2026.10.1 image. The initial eight practice checks passed five; three answers lacked exact supporting quotes. No candidate gain was accepted.

The 8B acquisition ended interrupted near the advertised total. The coordinator imposes a 300-second operation limit and cancels its child when exceeded; the session duration and interrupted state are consistent with that path, but the old session did not retain the precise cancellation cause. This change preserves an explicit limit explanation for future occurrences without increasing budgets or retrying automatically.

The later 14B candidate failed on its third practice answer with assistant-error. The original 4B model was restored. The original CLI adapter discarded stderr, so that exact failure cannot be attributed confidently. Ollama logs show earlier GPU discovery watchdog timeouts; they are startup evidence, not proof of the later answer failure. Future nonzero CLI exits retain bounded stderr in an owner-only local log, never in browser responses.

Watch fixes: render actual reply.text; suppress the previous answer while the current task is pending; completed counts cannot exceed the suite total; show acquisition percentage and hide stale challenge content; explain receipt checks; show blocked/options-exhausted summaries, current kept model, and failed attempts. The user sees no claimed gain after an incomplete comparison.

Verification: Auto Climb coordinator tests, assistant-trial tests, Node presentation regressions and existing Chromium fixture browser smoke, including download and blocked mobile captures. Fixture results do not establish real model improvement, incremental streaming, physical GPU or Firefox acceptance.

Remaining product work: persistent before/after scorecard throughout the run; visible ladder movement after validated gains; narrative transitions that explain each candidate; actual incremental assistant output if the gateway supplies it. Do not animate invented tokens.


## Physical follow-up on Toronado

The first patched live run completed its 14B practice retest: zero gains and two regressions, so the coordinator restored the original 4B model. The 8B acquisition again ended interrupted after its weight transfer; the cause is still unconfirmed. Private onboarding exception-chain diagnostics now preserve evidence for the next explicitly bounded test.

The live run also exposed an attempt-accounting bug: the final reserved slot was treated as exhausted during its own checks. The cap now applies before choosing a new candidate, while the duration cap remains enforced during every turn and child operation. Failed attempts still consume slots. A regression verifies that a one-attempt session actually finishes exactly one attempt.

Proposal selection now tries the reviewed quote instruction before a model download when at least two misses are all correct, direct answers missing exact source quotations. Mixed failures retain the existing model policy. This changes proposal order only; independent validation, gain thresholds, exposure tracking and Keep/Restore remain unchanged.


Four additional authored validation packs (val-p5 through val-p8) provide disjoint passages and questions after the first four packs were consumed on Toronado. Original packs, scorers, acceptance thresholds and exposure history are retained without resets. New packs use the same three answer, three missing-information and two everyday-control checks. This is still a finite reading/grounding curriculum, not evidence of broad ability or unlimited climbing.


A new approved climb can resume one retained paused/interrupted job for the same exact catalog tag and freshly checked store. Cancelled and failed integrity jobs are excluded. The normal verified acquisition pipeline is retained, and failed attempts continue to consume the session budget. Acquisition UI distinguishes transfer, verification, loading, reply check and publishing; it does not call downloaded bytes a ready model.


The next physical run exposed a duplicate-instruction proposal: the reviewed quote block was already installed. Selection now excludes instructions already present in AGENTS.md. A direct isolated OpenClaw probe confirmed AGENTS.md was fully injected without truncation, while the 4B answer still omitted a quote. This is behavior evidence, not a missing-bootstrap-file diagnosis. No validation pack was consumed and no mutation occurred in that blocked attempt. Coordinator exception chains are now retained privately for future failures.
