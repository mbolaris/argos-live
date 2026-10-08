# Implementation handoff: your private AI proving ground

> Current entry point: [WORKER-PLAY-SESSION.md](WORKER-PLAY-SESSION.md).
> It supersedes the historical J1 work order and image status below.
> [CURATED-MODEL-JOURNEY.md](CURATED-MODEL-JOURNEY.md) defines the smaller shortlist.
>
> October 8 update: J1/J2 implementations merged in PR58/59. Do not start them
> again from the historical instructions below. The current work order and
> first mission are specified in [Mission 1 implementation](PROVING-GROUND-MISSION-1.md):
> J5 → J6a/J6b → J7 → J3 → J8, with thinking/context later and J4 separately.
> Read that specification and the current backlog before implementing.

Owner intent and engineering guidance, October 7, 2026. This document is sufficient
for an implementation agent that has only this repository. Private Yugo outputs,
SSH credentials, raw USB backups and the owner's personas are intentionally absent.

## Product outcome

The owner has booted the persistent image on Toronado. The dark responsive UI is
working but still feels like administration rather than a compelling game of
improving a personal AI. The desired loop is:

**Choose a skill → watch the test → understand the result → configure an upgrade
→ repeat the same test → keep or restore.**

Use “your AI” in generic copy, including “How far can your AI go?” Argos Live is
the product name. A chosen agent name belongs on its identity and voice. Aim for
mission control: exciting observable work and earned progress, restrained copy,
no invented AGI percentage, XP, IQ, spending rewards or fake learning. The model's
reflection is opinion; code validates the scored result.

## Read first and current scope

- `docs/BACKLOG.md`: repository rules and J1–J4, P8a–P8b acceptance criteria.
- `docs/PERSONAL-ROBOT-EXPERIENCE.md`: Product focus and Meet your AI sections.
- `docs/GUIDED-MODEL-LAB.md`, `docs/GUIDED-MODEL-SELECTION.md`.
- `docs/MODEL-STORAGE.md`, `docs/MODEL-CATALOG.md`, `docs/MODEL-PULL-JOBS.md`.
- `docs/PROFILE-SYNC.md`: reuse reviewed persona staging/apply/rollback.

Verify current main and read code rather than trusting old status paragraphs.
The original handoff dated October 3 describing missing catalog/lab/switching was
obsolete: those systems now exist. Do not rebuild them. PR55 merged the dark UI,
document mission rail, examples and optional aggregate-metric local-model debrief.
PR56 merged the first identity-editor plan; this handoff PR adds the J1–J4 focus.

The installed October 7 image was build 37662687276, source
119dee6aa446b7e8ad3926e56bb6da87979385ca, 4,085,645,312 bytes, SHA256
bdd9ce850abd9055fe1517171abaa092a15760b21659a10e16238c2d9f97114c.
All source prerequisite checks passed. Local offline Windows WHPX trials actually
ran shipped Firefox, saved speed/ability results, resumed the assistant and
visually showed the new ladder/debrief. Hosted TCG run 37668053435 failed because
the gateway child exited 1 before listening; root cause is unconfirmed. Do not
claim hosted acceptance or weaken deadlines to make a green run.
The personal Kingston was subsequently updated with full-device readback and
unchanged encrypted ciphertext/partition metadata checks; the owner reports it
running. This does not establish new-image physical GPU, persona, conversation
recovery, firmware or browser-submitted chat acceptance. None is a UI fixture claim.

## Work in small deliverable slices

Start with **J1**, not another cosmetic home-page rewrite. Build one vertical slice
where a real local model takes the existing quick suite, observable answers and
per-item scored receipts appear while it runs, and cancel/reconnect are safe.
Then deliver J2 (map/result replay), J3 (model/storage journey), J4 (actual sandbox
tool tasks). Do not try to implement the entire historical backlog in one PR.
Identity P8a can follow the core watch-test loop; P8b follows verified isolation.
If an item exceeds one session, split its acceptance into explicit scoped PRs.

### J1 entry points and suggested architecture

- `runtime/argoslive/lab.py`: owns the workload reservation, phases, cancellation,
  pause/restore and snapshot. Preserve this ownership; a browser disconnect must
  not start another test, orphan services or create a new reservation.
- `bench_ability.py`: `execute` already reports item id, completed/total, elapsed
  and estimated time, but retains only phase-level progress in the Lab view.
  Scorers and saved item records already exist. Extend their callback data safely.
- `bench_speed.py`, `doc_trial.py`: existing runners and fixed scored suites.
- `ollama.py`: existing streaming generate callback and bounded stream handling.
  Inspect the exact signature and decoded fields; forward answer output only,
  not thinking fields or arbitrary backend messages. Do not change deterministic
  benchmark prompts/options or token limits merely to create entertainment.
- `web/server.py`: authenticated `/api/lab` and benchmark routes. A bounded event
  journal with run identity, increasing sequence and cursor reconnect is a
  reasonable first implementation; short polling is acceptable. SSE is optional,
  not a requirement to introduce a framework. Signal lost history on buffer gaps.
- `web/static/index.html`, `app.js`, `style.css`: live arena and accessible controls.

Recommended event types: phase, item-start, answer-delta, item-scored, final,
cancelled/failed. Fix schema, allowed fields and size/rate/event-count bounds. Use
server run identity plus sequence to avoid mixing old and new runs. Publish only
original public suite material; do not export owner pasted documents, profile
content, paths, tokens, configs or raw exception text. Preserve separate memory-
only owner-task handling. Completed evidence remains in existing results storage;
transient streams are not another authoritative score database.

Show the challenge, streamed answer, completed count, elapsed time and growing
receipts. Unknown-duration setup/restoration uses named phases, not invented
percentages. Use a scored receipt to explain format errors versus wrong answers.
Stop remains visible. Keep partial/cancelled results visibly incomplete.

### J2 and J3: reuse evidence and transactions

- `command_center.py`, `mission_report.py`, `journal.py`: existing next action,
  evidence states, scoped report and opinion. Never let opinion color qualification.
- `results.py`, `web/benchmarks.py`: matched comparisons and records. Preserve suite,
  version, context/settings, coverage and matching hardware checks. Current model
  qualification binds to tag plus manifest digest, not tag alone.
- `storage_view.py`, `reboot_evidence.py`, `model_selection.py`, catalog and existing
  download controls: verified location choice, gate, exact identity, switch/restore.

Map useful task nodes under understanding, reasoning, planning, tools, memory and
perception. Existing small probes qualify only their declared tasks. Future suites
stay disabled/unassessed. Labels/icons accompany color; phone users get the same
map as a navigable grouped list. Make fixed criteria and actual failed answers easy
to inspect; keep JSON and technical inventory behind Advanced.

“Try a different model” starts an inline reviewed-catalog flow. Show a small set
of candidates with download size and advisory hardware fit, not “bigger is smarter.”
If storage is needed, show “Choose where to keep models,” labeled eligible drives,
free space, encryption/persistence and a justified eligible recommendation. Review
then “Use this location” confirms the destination and write check. Explain blocked
choices and allow keeping the bundled starter. Never choose by old drive letter,
format a drive, auto-adopt DATA or silently relocate an existing store. Profile and
history remain separate from unencrypted model DATA. Then verified download,
explicit switch, matched retest, Keep/Restore. Do not invent a catalog identity for
“Qwen3.8 27B”; exact upstream model identity/license/digest needs its own review.

### J4 and identity boundaries

Tool-call format probes are not agentic execution. J4 needs an opt-in disposable
sandbox, allowlisted actual tools, public original fixture, bounded action/time
budget, code-verified artifact and visible action/outcome trace. Validate pinned
OpenClaw permissions end to end before broadening anything. No host personal files,
network or unrestricted shell; no hidden chain-of-thought. Failure is useful evidence.

P8a edits display name and reviewed persona, previews the same public conversation,
saves explicitly and offers scoped restore. Preserve internal IDs, models, tools,
credentials and conversations. Check pinned upstream schema and reuse pack machinery
instead of adding a conflicting profile store. Guest changes are temporary; encrypted
storage configuration and actual reboot recovery are separate claims. P8b can use a
reviewed persona in bounded tool-disabled debriefs only after isolation is verified.

## Validation and delivery

Follow BACKLOG rules: branch/PR per scoped item, stdlib Python, pinned dependencies,
loopback/token protection and no private data. Preserve any local owner changes,
especially `runtime/argoslive/data/documents/short.json`; it is a real owner edit in
the original Yugo checkout. Never discard it or regenerate suite criteria silently.

Run meaningful unit tests for event bounds/cursor gaps/stale run isolation/cancel,
privacy filtering, adversarial escaped output and preserved score comparability.
Run `bash scripts/check.sh` on Linux; report root-only skips honestly. Existing
`scripts/smoke-dashboard-browser.mjs` and `smoke-journey-browser.mjs` are Chromium
fixture tests, not shipped Firefox or real inference. Add assertions for live
updates and 320/390/768px layouts, inspect screenshots and keyboard/Stop behavior.
Then exercise a real pinned local model. Native/model CI triggers must cover changed
runtime files; a silent skipped smoke is not a pass. No broad repetitive test runs
after success unless another change or unresolved failure warrants them.

Open PRs with what works, tests and remaining limits. Merge only when authorized;
do not infer future PR merge authorization from historical merges. When runtime/UI
changes have landed, coordinate one new ISO build from exact main with the local
deployment agent. If authorized to dispatch, first check no matching run exists.
Record every run/download session. Verify full ISO checksum/size/source/package
manifest/runtime pins, then exact-build managed acceptance using current workflow
inputs. Review actual Firefox and real trial output; listener/title is insufficient.

You only have the repo: **do not attempt the physical USB update**. Deliver source,
PR/check/build IDs, verified artifact identifiers, exact acceptance results and
remaining checks to the local Yugo agent. Yugo must independently identify the
device, make a fresh current backup and validate preservation/geometry before
writing. Never copy private profiles into the generic image or reuse old raw backup
receipts as fresh proof. Physical deployment is a separate owner-authorized action.

## Consultation and reporting

The original Yugo chat remains available to consult on product tone, priorities,
evidence rules and local image/device validation. Ask the owner to relay a concise
question there when needed; access to that chat or unsolicited messaging is not
assumed. Resolve routine implementation choices yourself using this document.
Report progress as completed acceptance, concrete failures and next deliverable,
not a narration of every edit. Start with J1 and produce a reviewable working slice.
