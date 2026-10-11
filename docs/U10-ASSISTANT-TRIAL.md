# U10 — one reversible, measured change to the everyday assistant

The lab improves how Argos *tests* a model. U10 is the first change to the assistant the owner actually talks to, and it must earn its place there on its own evidence. Lab results never promote it.

## What exists and is reused

- **Assistant:** OpenClaw 2026.9.8 gateway with the reviewed local profile (`~/.openclaw/openclaw.json`: minimal tools, deny list, no elevated, no bash/restart, no channels; `startup.source` refuses anything else).
- **Persona:** workspace bootstrap files injected into every new session: `AGENTS.md` (operating instructions), `SOUL.md`, `IDENTITY.md`, `USER.md`, and `MEMORY.md` when present. OpenClaw has no global system-prompt key and no extra bootstrap file, so a reviewed instruction can only enter through these files.
- **Transactions:** `model_selection` already does journal → stop → write → start → wait for a verified reply → keep a rollback record → Keep/Restore. Owner edits block automatic restore, and an unfinished journal is resolved at the next desktop start. U10 copies this shape for one file.
- **Assistant path:** `openclaw agent --agent main --session-id <new> --session-key agent:main:argos-trial-<new> --message … --timeout 120 --json` runs one turn through the running gateway with the normal workspace bootstrap. This is the everyday-assistant path, not the lab's direct Ollama calls. No thinking, model or delivery override is supplied. The pinned installed CLI implementation was inspected read-only on Toronado: explicit scoped keys are routed to the gateway, with no implicit local-execution fallback. Real trial execution remains unverified until authorized physical acceptance.

## The one change

**Grounded answers** (`grounded-answers` v1), appended to `AGENTS.md` inside an Argos-managed block:

```
<!-- argos-trial:grounded-answers v1 — added with your approval; Argos Live can restore the original file -->
## Answering from text you were given
When I give you a document, notice or passage and ask about it: answer directly first, in a short phrase or sentence. Then quote the sentence from the text that supports your answer. If the text does not contain the answer, say so plainly instead of guessing.
<!-- /argos-trial:grounded-answers -->
```

- **Scope:** questions about text the owner provides in chat. No model, tool, permission, channel, personality or setting change. `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `openclaw.json` and `state.json` must be byte-identical before and after (checked). Main-agent workspace overrides are resolved; behavior overrides beyond the reviewed defaults are refused. Oversized or linked instruction files and a block beyond the bootstrap character limit are refused.
- **Expected benefit:** direct answers to document questions, with a quotation the owner can check, and an honest "the text doesn't say" instead of a guess.
- **Why this change:** the audit (`DOCUMENT-MISS-AUDIT.md`) showed qwen3:4b quotes reliably but buries short answers in full sentences when asked for structured output. That observation motivated the change. It is **not** evidence that the change helps the assistant: the lab instruction "strict format" was tried and restored, and no lab result is used below.

## Approval

The Improve page shows one compact "Try in your everyday assistant" card (no new dashboard). Its dialog shows the exact text, the file it goes into, what stays unchanged, the independent tasks it will run, and that chat restarts when applying or restoring. Nothing changes until **Approve and run the assistant trial**. This is an independently approved assistant experiment; a successful lab result is not a prerequisite or proof.

## Trial (one approved run)

1. **Gates:** no other workload; the assistant is ready with a verified reply; no unfinished journal; the reviewed profile passes; the `AGENTS.md` and protected-file hashes are recorded.
2. **Before:** run the independent tasks through the assistant path (current configuration), one fresh session per task.
3. **Stage:** write the journal (raw `AGENTS.md` before/after, protected hashes), stop the assistant, append the block atomically, start the assistant, and wait for a verified reply.
4. **After:** run the same tasks in fresh sessions.
5. **Verify:** protected files unchanged; `AGENTS.md` equals the staged bytes. An ordinary failure restores the original bytes and restarts, with verification before clearing the journal. Owner edits block automatic recovery: keep their bytes, stop the assistant and retain the journal for review. Never claim a restore that failed.
6. **Decision:** the change stays applied, marked *on trial*, until the owner chooses.

## Independent tasks

`runtime/argoslive/data/assistant-trials/grounded-answers.json`: original public passages unrelated to the document suite (no shared passages, questions or answer strings), asked the way an owner would in chat, without mentioning quotes.

- **3 document questions with answers:** checks are *answer present* (an accepted fact outside long quotations, whole words), *answer first* (within the first 25 words of that answer text), and *exact quote* (a quoted span of 15 or more characters found verbatim in the passage and containing an accepted fact). A correct citation alone cannot rescue a wrong answer field.
- **3 document questions the text cannot answer:** check *admits it isn't stated*.
- **2 everyday controls without a document:** check *no instruction leak* (no talk of quotes or passages). This is the regression guard for ordinary conversation; it also records whether the reply is non-empty.

Checks are code, reported per task and per check. The change text contains no task answers. They are limited text heuristics, not semantic correctness guarantees or a general ability score. Before/after use identical prompts and fresh scoped sessions. Replies are retained in full up to a 6,000-character inspection limit; longer output stops the trial instead of hiding scored evidence.

While an approved trial is running, the watch view shows the current before/change/retest stage, completed task count, current question and source notice, then the most recent completed reply paired with the question that produced it. Eight progress pips indicate completed prompts, not qualified skills. It updates after each gateway turn; the CLI does not stream tokens, so the interface must not imply that it does. Partial live progress is in memory only and is not treated as a completed trial result.

## Result shown to the owner

Before → after per task and check; **gains** (fail → pass), **regressions** (pass → fail), reply time, and an explicit uncertainty note: one run per task, 8 tasks, sampling varies, so a difference of one task is not meaningful. A suggestion is shown only as a suggestion: consider keeping if at least two tasks gain checks and none regress, otherwise restore. Even two gains do not establish statistical significance. Evidence records the model, profile hash, task version/hash and exact instruction hash. Assistant evidence is labeled "everyday assistant"; it never appears in lab scores and lab scores never appear in it.

## Keep or Restore

- **Keep:** record the change in `~/.config/argos-live/assistant-changes.json` (original and applied bytes, hashes and time), clear the journal, and verify the file. Restore stays available while `AGENTS.md` still equals the applied bytes.
- **Restore:** refuse if the owner has edited `AGENTS.md` since (the owner is told to review it by hand). Otherwise stop, write the original bytes, start, wait for a verified reply, and verify `AGENTS.md` matches the original and the protected files are unchanged.
- **Crash:** an unfinished trial or Restore journal found at desktop start restores the original bytes only if file/schema/change/protected identities match. Otherwise startup is blocked for review. A valid trial awaiting a decision remains on trial. Restore from a kept change also writes a journal before stopping, so failed restarts remain recoverable. Private errors go to `~/.config/argos-live/assistant-trial-error.json`, never HTTP.

## Also in this change

The "next action" no longer recommends a larger model when every miss kept an accepted answer (diagnostic groups *wording* and *requirement* only). It suggests stepping through the misses instead and says plainly that "Right meaning, rejected for wording" is a diagnostic classification, not a score.

## Acceptance

- Unit tests: block apply/restore is byte-exact; protected-file and owner-edit guards; crash recovery; task scoring per check on recorded replies; gain/regression arithmetic; journal and record schemas; routes are authenticated and empty-bodied.
- Fixture browser smoke: approve → before → staged → after → result → Keep (record verified) → Restore (original bytes verified), plus cancellation and stable opened evidence across polling, using a fixture assistant runner, never a real model. Simulated previews are labeled.
- `command_center` and Improve no longer recommend a model candidate for wording-only or requirement-only misses.
- Not in this PR: deployment, a real-assistant run on Toronado, physical phone, reboot. The first real trial on Toronado happens only after the owner approves it in the dialog.
