# Hands-off improvement loop: runbook and handoff

Written November 12, 2026 for whoever operates the loop next. Read
[HANDS-OFF-STANDING-ORDERS.md](HANDS-OFF-STANDING-ORDERS.md) first: it says what may run without
asking the owner and what still needs approval. Those orders bind you too, and the owner can change
them at any time.

## The goal

The owner wants to sit back and watch Argos try to improve, without the Live drive being rebuilt for
every Python or web change and without being asked to take part in each step. Image rebuilds and SSD
writes are now reserved for operating-system and boot changes.

## Machines and access

- **Toronado** (192.168.1.46): the production machine. Boots the Argos Live SSD with encrypted
  persistence. Only the owner enters the passphrase, at Toronado, in the masked local window.
- **Yugo** (192.168.1.31, Windows): the owner's workstation and where you run these tools.
- Reach Toronado only through the strict-pinned SSH helper (`ARGOS_REMOTE_HELPER` below). Never accept
  a changed host key, never ask for the passphrase in chat, and never put it in a file or argument.

## Tools (scripts/hands-off/)

- `runtime_update.py build <commit> <base_commit>` makes a bundle of `runtime/argoslive` for a commit on
  `origin/main` plus a receipt with before and after digests. The receipt is `verified` only when every
  GitHub check on the commit passed; otherwise the files are named `-unverified` and
  `apply_update.py` refuses them. `rehearse <receipt>` runs apply, rollback and the refusals on a
  local copy.
- `apply_update.py apply|health|rollback <receipt.json> <stamp>` pushes the bundle to Toronado, swaps
  the tree atomically with a snapshot, restarts only the desktop process (graceful SIGTERM, no
  reboot), runs the health check, and rolls back on failure.
- Output goes to `work/hands-off/` (git-ignored), or to `ARGOS_HANDS_OFF_DIR`. Set
  `ARGOS_REMOTE_HELPER` to the pinned helper (on Yugo:
  `work/proctor-level2-20261019/remote.py`). Run both scripts with a Python that has no extra
  dependencies; the records backup tool needs one with `cryptography`.

Order for an update: take an encrypted records backup, build and rehearse, `apply`, `health`. The
health check passes only if the installed tree matches the bundle, the new routes answer, the
assistant is ready, and a `quick` evaluation completes with saved evaluations. It then finalizes
(deletes the kept previous tree; the snapshot archive stays under
`/var/lib/argos-live/runtime-updates/snapshots`).

At boot, `argos-refresh-runtime.service` re-syncs image-owned files from the Live image. The
version-aware refresher implementation is merged in `main` via PR #177: after a runtime update
passes health, the updater records the exact image runtime digest and installed runtime digest.
On a later boot, the refresher preserves that runtime only when both still match; a changed image
or changed installed tree falls back to the image. This records exact image identity rather than
guessing which source commit is newer. The successful deployment is recorded below.

**Deployment check, November 14.** With owner approval, PR #183 (`161ea355`) fixed the boot
wrapper's import selection and made the systemd unit call the persistent wrapper. A persistent
systemd drop-in now selects `/usr/local/sbin/argos-refresh-runtime`; no reboot or service restart
was needed. The wrapper chooses the immutable package for ordinary refreshes and the installed
package when a valid version-aware override is present or being recorded. Its legacy rollback path
accepts `--record-override` only if the installed and image package trees match exactly.

Runtime bundle `161ea355` was built against base `6c89bcb` (expected pre-update tree
`e83a6da2…`, 107 files), rehearsed, and applied. Installed tree digest is `4c9e4645…` (126 files).
The updater's quick health campaign completed two matched `quick/1.0.0` runs at 20/20, saved runs
`4c5b0406256ba55ce31d75e1d09717fb` and `1341565283371ba95a29aece18bbc236`, and passed both audits.
This is an operational health check, not evidence of an owner-task improvement. The version marker
was independently checked read-only against both runtime trees and is valid:
image `420b2024513cb795dc72b38bb37dbbe57fd97f8e982410a053a5c9c64ed0bb14`, installed
`2f4cb87df430e7873f0176b1249d7f26f14d1aee758299fb924100ca176c09f2`. The wrapper hash is
`59a0bb2679c5f00804d716b594b897842388393863d1d9befb576fcd6da68f87`; systemd's effective
`ExecStart` selects it. The records backup at
`work/ssd-boot-20261023/postboot/records-20261114T140016Z.encrypted.json` passed authenticated
decryption and all 440 manifest hashes. The earlier pre-refresh snapshot remains available at
`/var/lib/argos-live/runtime-refresh/runtime-refresh-20261114T040421Z-a7b71ae6a55f/`.

## Latest owner-task evidence (November 14)

**Follow-up summary-format campaign.** The `documents-short/1.1.0` campaign restored the original
instructions after testing the request to produce exactly two sentences
without an unsolicited quote. Baselines `42191eaf64824f0f800fc4a348d3075d` and
`13c91208447544d8aabeef7d15f6cf81` scored 24/32 and 25/32 overall; their summary scores were 4/8
and 5/8, with 4 and 3 format errors. Candidates `09e3f3f6c06c2f48fe22db29fd322f65` and
`8f463554860b47b02ba5d9736ba9bf2a` each scored 28/32, summary 8/8, and zero format errors. All
four runs scored answer 8/8, quote 4/8, and not-stated 8/8. The restore audit passed and
`AGENTS.md` returned to SHA-256
`6f4b3de42f66df478783af4e72c154f3b193d770f85ed27a733d30a4d35d1453`.

The host keep policy then in use, `argos-practice-keep/4`, had no `documents-short` rule, so this
suite could not pass the host keep gate. With owner approval on November 14, PR #186 added
`argos-practice-keep/5`, preserving v4 and adding a v1.1.0 category-level rule: both candidate
summary scores must beat the best baseline summary score, answer/quote/not-stated scores must not
regress from the best-summary baseline, and candidate format errors must not exceed that baseline.
The summary score is a narrow format-and-key-fact proxy, not a complete measure of summary quality.

Policy v5 was deployed to Toronado from PR head `953209990d1c45624192d7f34bb267a61cd034d8`
(merge commit `45945f19688ab80de00f536dfc0ab7c61877717b`). The encrypted records backup
`work/ssd-boot-20261023/postboot/records-20261114T173540Z.encrypted.json` passed authenticated
decryption and all 487 manifest hashes; its SHA-256 is
`b060fb910ed540b769ca37c74f44407aaabb87d20c724686ff521b528e99510e`. Health runs
`51e2c249dcf9923cd6354785386b92ec` and `10e7173d4e47e95d3112bb323341979b` both completed quick
at 20/20 and both audits passed. The installed runtime matches bundle digest
`29d7d4ef8f90b2b69a5e2b8c476190212f85b6a10ce3393473e1501792dba949` (126 files). No reboot or
model change was made.

After restore, the remaining quote cases (`quote-01` through `quote-04`) passed three of three
read-only repetitions each when the accepted answer values and quote requirements were supplied.
Together with the earlier `quote-05` through `quote-08` probe, this does not establish a
quote-retrieval weakness under those fair, supported conditions.

The `documents-short` Improve campaign `c32cfc348c25f196b07c80b876736c3e` completed with a
restore verdict. Baselines `1760e3f922fa3cb2d4452545be6187e4` and
`fcc87fd5e16c01a45f31a815c43dbc20`, and candidates `bbe01d009bed13980c27b1b733db35e6` and
`f74b9eb520ce61290134f94009010bd1`, all scored 20/24 on the same suite and model: answer 8/8,
quote 4/8, and not-stated 8/8. The eight summary entries are unscored. The audit passed and the
Toronado `AGENTS.md` SHA-256 remained
`6f4b3de42f66df478783af4e72c154f3b193d770f85ed27a733d30a4d35d1453`. No improvement was
established.

A fair, isolated quote probe supplied accepted answer values and quote requirements; quote-05
through quote-08 each passed three of three repetitions. The old quote misses therefore do not
establish a quote-retrieval weakness. A summary-format probe then used all eight original prompts
unchanged for three repetitions each. Eighteen of 24 replies appended an unsolicited source quote
after the requested two-sentence summary; only six ended after exactly two sentences. Per-item quote
append counts for summary-01 through summary-08 were 1/3, 2/3, 2/3, 3/3, 2/3, 2/3, 3/3, and 3/3.
Summaries have no scorer, so this is a candidate instruction-following weakness only, not a measured
gain or loss. At this 07:17 UTC snapshot, the owner had not selected the next task; the later
delegation and follow-up campaign are recorded above.

The Yugo mirror at `127.0.0.1:8765` was responding with no error at the latest check on November 14
at 07:17 UTC (snapshot age 12 seconds); its snapshot showed the campaign inactive and Argos ready.
Main native-chat run
`43564638085` failed the CPU-placement check after reporting split placement (4.4 GB model,
434,645,237 VRAM bytes). The Proctor practice step passed, and later model checks were skipped.
The PR #180 checks and its post-merge tests and compatibility checks passed; PR #181 refreshed the
runbook and backlog status, with its checks and post-merge tests passing.

## State as of November 12, 2026

- `main` is at the merge of #171. Toronado runs `main` commit 6900d75's runtime (tree digest
  `97eea4eb…`), applied and health-checked. The Live drive has the quirk fix baked into its boot menu
  (`usb-storage.quirks=0bda:9201:u`); see docs/USB-SSD-UAS.md.
- `AGENTS.md` on Toronado is the journal-verified version (sha256 `94b8ce2f…`). The edit Argos made to
  it outside the managed tool (sha256 `364ef7b8…`) is preserved unchanged on Toronado under
  `~/.local/state/argos-live/quarantined-edits/`. It rewrote the evidence rules, improvement order
  and stop conditions and added a Lessons section; treat it as an experiment to test, not an
  improvement.
- An Auto Climb session started November 12 with the envelope 8 hours, 12 experiments, no model
  downloads. Check it with `GET /api/auto-climb` (header `X-Argos-Token` from
  `~/.local/state/argos-live/desktop-session.json`).
- GitHub Actions had not started any run for about 8 hours on November 11 to 12. The owner accepted a
  clean local full-suite run as the gate for the 6900d75 update. On Windows, 5 of 1,133 tests fail for
  platform reasons (path separators, POSIX modes, a charmap decode, a read-only store); Linux CI is the
  real gate when it works.

## Open work, in order

1. Done (November 12): Auto Climb practice saturated twice. Tier 1 (`argos-foundation/1`) and the
   near-miss tier 2 (`argos-foundation/2`, delivered as `main` 29be654, tree `a1d7449a…`) both scored 8/8,
   and session 6de8dfdf stopped in 5 minutes with "Practice saturated… Nothing was changed."
   A headroom probe on Toronado (48 isolated turns, nothing saved) found the model passes long notices
   with look-alike distractors, corrected or superseded facts, false-premise questions and missing
   details. It misses strict answer formats about a third of the time: the value is right, but the kept
   "show the source" habit appends a quoted sentence ("B \"Dr. Mendes works only…\""). So tier 3,
   `argos-foundation/3` (exact formats), asks for one letter, yes or no, a number or an ISO date in six of
   eight challenges, with one quoted answer and one unanswerable question to catch a change that breaks
   quoting or honesty. Its candidate, "Follow the requested format" (`exact-format`), generalizes the
   first Lessons line Argos wrote for itself and is tried first when the misses are right-value,
   wrong-format. Delivered November 13 as `main` 01892a9; session 17471eae scored tier 3 at 8/8 on one
   run and stopped saturated, but three repeat runs with the same instructions and model scored 7, 6 and
   5 of 8 (every miss a right value with a quote appended). A tier now counts as saturated only after
   three perfect practice runs in a row (`SATURATION_RUNS`); otherwise the first imperfect run is the
   baseline. Next: deliver that, start a session, and read the verdict. The keep policy is unchanged.
2. Of the `AGENTS.md` edit Argos made on November 8, the one-letter Lessons line is now measured by
   tier 3 (as the broader `exact-format` rule). The JSON line (lowercase format names in tool
   arguments) needs a tool-call task family; the embedded trial runner is tool-free. Its rewrites of
   section 2, section 3A and the stop conditions would loosen the keep standard; they are an owner
   decision, not an experiment.
3. Closed: the tool-schema 1/40 and 0/40 runs used suite v1.1.0, which expected `name` where the model
   wrote `tool`. Suite v1.2.0 scores 40/40. Different suite versions are not a matched comparison.
4. Done on Yugo (November 14): read-only watch mirror at `127.0.0.1:8765`. The version-aware boot
   refresher is in `main` via PR #177 but has not been deployed successfully; see the deployment
   check above. The immutable image's older module restored the base runtime during health.
5. Shakedown Phase 1 is delivered. SIM37/38/39/40 foundations and SIM41's result screen are merged
   (PRs #177, #178 and #179). SIM42's persistent lap queue is merged; fixture checks cover sequential
   execution, missing-model preflight, cancellation, reboot recovery, and unchanged deployed
   configuration. SIM43's local export and complete-lap personal bests were merged in PR #180.
   No model evaluation has run on Toronado. The dashboard starts laps only
   after an owner clicks Run or Start queue. The owner-selected improvement campaign remains idle
   until the owner chooses a task. Design rules: real-world sci-fi, the typical user is an amateur LLM
   enthusiast tuning a local agent, and the bench comes first.

## Standards that must not slip

- One evaluation at a time. Snapshot before changing Toronado, and take a records backup before any
  power-off.
- Keep or roll back by the preset keep policy only (`instruction_changes`, policy argos-practice-keep/5).
  Policy v5 preserves every v4 rule and adds a category-level gate for `documents-short/1.1.0`:
  both candidates must beat the best baseline summary score, answer/quote/not-stated scores must
  not regress, and candidate format errors must not exceed the best baseline's.
  The last generic instruction trial went from 37/40 to 39/40 twice but missed its preset threshold and
  was rolled back. Keep that standard of evidence. Argos owns its model and instruction experiments.
- Ask first, every time, for: boot-area or SSD writes, new images, reboots or power-off, model
  downloads, SSH or permission changes, deleting owner data, and merging PRs that touch image, boot,
  SSH, permissions or containment.
- Stop the loop and report on a kernel storage or USB error, a failed health check,
  `recovery_required`, two consecutive failed evaluations, or the daily limit.
