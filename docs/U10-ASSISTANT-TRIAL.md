# U10 — one reversible, measured change to the everyday assistant

The lab improves how Argos *tests* a model. U10 is the first change to the assistant the owner actually talks to, and it must earn its place there on its own evidence. Lab results never promote it.

## What exists and is reused

- **Assistant:** OpenClaw 2026.9.8 gateway with the reviewed local profile (`~/.openclaw/openclaw.json`: minimal tools, deny list, no elevated, no bash/restart, no channels; `startup.source` refuses anything else).
- **Persona:** workspace bootstrap files injected into every new session: `AGENTS.md` (operating instructions), `SOUL.md`, `IDENTITY.md`, `USER.md`, and `MEMORY.md` when present. OpenClaw has no global system-prompt key and no extra bootstrap file, so a reviewed instruction can only enter through these files.
- **Transactions:** `model_selection` already does journal → stop → write → start → wait for a verified reply → keep a rollback record → Keep/Restore. Owner edits block automatic restore, and an unfinished journal is resolved at the next desktop start. U10 copies this shape for one file.
- **Assistant path:** `openclaw agent --agent main --session-id <new> --session-key agent:main:argos-trial-<new> --message … --timeout 120 --json` runs one turn through the running gateway with the normal workspace bootstrap. This is the everyday-assistant path, not the lab's direct Ollama calls. No thinking, model or delivery override is supplied. The pinned installed CLI implementation was inspected read-only on Toronado: explicit scoped keys are routed to the gateway, with no implicit local-execution fallback. Real trial execution remains unverified until authorized physical acceptance.

## Reviewed starter ideas

The current starter set contains three small, separate changes to `AGENTS.md`: **Answer first**, **Show the source**, and **Be honest when it is missing**. Each has a stable ID and fixed instruction text in `assistant_trial.py`; model output cannot invent instructions or add permissions. One GO discloses and tests every currently untried idea in a single campaign.

- **Answer first:** put the direct answer in one short sentence before explanation.
- **Show the source:** add one exact supporting sentence to answers about supplied text.
- **Be honest when it is missing:** say when the supplied source does not contain the answer.

The initial round tests all three. After a winner is kept, the next action is to try the assistant on a real question; no second GO is needed to reach another starter idea. Already-tested ideas are recorded with the kept change and are not repeated as if new. If a prior two-idea record exists, the remaining untried idea is still offered. If no idea clears the win threshold, nothing new is recorded; another GO repeats the same set to check whether the result holds, or the owner can continue to chat.

The original **Grounded answers** (`grounded-answers` v1) block remains recognized so existing Keep/Restore records can be recovered. New rounds do not add that combined block.

Example of the reviewed `Show the source` block:

```
<!-- argos-trial:quote-evidence v1 — added with your approval; Argos Live can restore the original file -->
## Show the source
When answering a question about text I provided, give the answer and then quote one exact sentence that supports it. Never make up or alter a quotation.
<!-- /argos-trial:quote-evidence -->
```

- **Scope:** each candidate affects one narrow behavior only. No model, tool, permission, channel, personality or setting change. `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `openclaw.json` and `state.json` must be byte-identical before and after (checked). Main-agent workspace overrides are resolved; behavior overrides beyond the reviewed defaults are refused. Oversized or linked instruction files and a block beyond the bootstrap character limit are refused.
- **Expected benefit:** clear answers, verifiable source quotes, or fewer guesses when evidence is missing. Each idea is measured against the checks it targets; this does not establish broad intelligence.
- **Why this change:** the audit (`DOCUMENT-MISS-AUDIT.md`) showed qwen3:4b quotes reliably but buries short answers in full sentences when asked for structured output. That observation motivated the change. It is **not** evidence that the change helps the assistant: the lab instruction "strict format" was tried and restored, and no lab result is used below.

## Approval

The Improve page offers one focused card: one **GO** runs the whole bounded campaign. Before GO, it shows each idea's scope and expandable exact wording, the same eight questions in each comparison, the maximum answer count, the reset between ideas, and the files/settings that stay unchanged. The questions are expandable. Pressing **GO** is explicit approval for that exact plan; its idea IDs are sent to the controller, which refuses to start if the plan changed since it was shown. There is no redundant preview-then-approve dialog. Nothing changes before GO. This is an independently approved assistant experiment; a successful lab result is not a prerequisite or proof.

## Trial (one approved run)

1. **Gates:** no other workload; the assistant is ready with a verified reply; no unfinished journal; the reviewed profile passes; the `AGENTS.md` and protected-file hashes are recorded.
2. **Baseline:** run the independent tasks through the assistant path (current configuration), one fresh session per task.
3. **One idea at a time:** for each disclosed candidate, journal the exact bytes, stop the assistant, append that single block atomically, restart and run the same tasks in fresh sessions. Restore and verify the baseline before testing the next candidate. The session is capped at one baseline and three candidates (32 task answers total).
4. **Select:** only a candidate that improves at least two challenges without a regression can be recommended. If multiple qualify, use the fixed score ordering; apply only the leading idea again for the owner's Keep/Restore decision. If none qualifies, restore the original or prior-kept bytes and report the no-win result. No idea is silently kept.
5. **Reflect:** ask the selected local model for a bounded opinion using aggregate check counts for each idea only. No raw replies, personal profile, tools or hidden reasoning enter this prompt. This opinion cannot change scores or the controller's Keep/Restore recommendation. Failure to produce an opinion does not discard the scored result.
6. **Verify:** protected files unchanged; `AGENTS.md` equals the staged bytes. An ordinary failure restores the exact pre-round bytes and restarts, with verification before clearing the journal. Owner edits block automatic recovery: keep their bytes, stop the assistant and retain the journal for review. Never claim a restore that failed.
7. **Decision:** the leading idea stays applied, marked *on trial*, until the owner chooses. Keep records all ideas tested in that campaign, so the next action advances to a real task; Restore unwinds the kept choice and its history.

## Independent tasks

`runtime/argoslive/data/assistant-trials/grounded-answers.json`: original public passages unrelated to the document suite (no shared passages, questions or answer strings), asked the way an owner would in chat, without mentioning quotes.

- **3 document questions with answers:** checks are *answer present* (an accepted fact outside long quotations, whole words), *answer first* (within the first 25 words of that answer text), and *exact quote* (a quoted span of 15 or more characters found verbatim in the passage and containing an accepted fact). A correct citation alone cannot rescue a wrong answer field.
- **3 document questions the text cannot answer:** check *admits it isn't stated*.
- **2 everyday controls without a document:** check *no instruction leak* (no talk of quotes or passages). This is the regression guard for ordinary conversation; it also records whether the reply is non-empty.

Checks are code, reported per task and per check. The change text contains no task answers. They are limited text heuristics, not semantic correctness guarantees or a general ability score. Before/after use identical prompts and fresh scoped sessions. Replies are retained in full up to a 6,000-character inspection limit; longer output stops the trial instead of hiding scored evidence.

While an approved trial is running, the watch view shows the current before/change/retest stage, completed task count, current question and source notice, then the most recent completed reply paired with the question that produced it. Eight progress pips indicate completed prompts, not qualified skills. It updates after each gateway turn; the CLI does not stream tokens, so the interface must not imply that it does. Partial live progress is in memory only and is not treated as a completed trial result.

## Result shown to the owner

Each idea gets a side-by-side plain-language scorecard: challenges improved, unchanged or worse, plus its target check count. The recommended idea is selected by the fixed threshold and tie-break order; all other results remain available. One run per task means small differences are noisy and are not proof of general improvement. The selected model can add a short first-person opinion based only on aggregate counts; it is prominently labeled as opinion and displayed separately from scored facts. The code recommendation remains authoritative. Evidence records the model, profile hash, task version/hash and exact instruction hash. Assistant evidence is labeled "everyday assistant"; it never appears in lab scores and lab scores never appear in it.

## Keep or Restore

- **Keep:** record the winning change and the full set tested in `~/.config/argos-live/assistant-changes.json` (original and applied bytes, hashes, time and prior record), clear the journal, and verify the file. Restore stays available while `AGENTS.md` still equals the applied bytes. The next round skips already-tested ideas.
- **Restore:** refuse if the owner has edited `AGENTS.md` since (the owner is told to review it by hand). Otherwise stop, write the original bytes, start, wait for a verified reply, and verify `AGENTS.md` matches the original and the protected files are unchanged.
- **Crash:** an unfinished trial or Restore journal found at desktop start restores the original bytes only if file/schema/change/protected identities match. Otherwise startup is blocked for review. A valid trial awaiting a decision remains on trial. Restore from a kept change also writes a journal before stopping, so failed restarts remain recoverable. Private errors go to `~/.config/argos-live/assistant-trial-error.json`, never HTTP.

## Also in this change

The "next action" no longer recommends a larger model when every miss kept an accepted answer (diagnostic groups *wording* and *requirement* only). It suggests stepping through the misses instead and says plainly that "Right meaning, rejected for wording" is a diagnostic classification, not a score.

## Acceptance

- Unit tests: block apply/restore is byte-exact; protected-file and owner-edit guards; crash recovery; task scoring per check on recorded replies; gain/regression arithmetic; journal and record schemas; routes are authenticated and empty-bodied.
- Fixture browser smoke: review the exact three-idea plan → one GO → baseline and each isolated candidate with visible progress → side-by-side results and opinion → Keep one winner → direct real-question next step → Restore to byte-exact prior state, plus cancellation and stable opened evidence across polling. Uses a fixture assistant runner, never a real model; simulated previews are labeled.
- `command_center` and Improve no longer recommend a model candidate for wording-only or requirement-only misses.
- Not in PR #86: deployment, a real-assistant run on Toronado, physical phone, reboot. Fixture browser evidence is not real-model evidence. Any real trial still needs the owner's explicit GO on the device.
