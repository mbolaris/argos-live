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

Reboots reset the runtime. `argos-refresh-runtime.service` re-syncs the tree from the image at boot,
so after any reboot you must re-apply the bundle. Making that refresher version-aware is open work.

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
4. Build the read-only watch mirror on Yugo, and make the boot refresher version-aware.
5. Shakedown (docs/shakedown/DESIGN.md and BACKLOG.md): Phase 1, the bench, is the next feature work.
   Design rules: real-world sci-fi, not fantasy; the typical user is an amateur LLM enthusiast tuning a
   local agent; bench first, spectacle second.

## Standards that must not slip

- One evaluation at a time. Snapshot before changing Toronado, and take a records backup before any
  power-off.
- Keep or roll back by the preset keep policy only (`instruction_changes`, policy argos-practice-keep/4).
  The last generic instruction trial went from 37/40 to 39/40 twice but missed its preset threshold and
  was rolled back. Keep that standard of evidence. Argos owns its model and instruction experiments.
- Ask first, every time, for: boot-area or SSD writes, new images, reboots or power-off, model
  downloads, SSH or permission changes, deleting owner data, and merging PRs that touch image, boot,
  SSH, permissions or containment.
- Stop the loop and report on a kernel storage or USB error, a failed health check,
  `recovery_required`, two consecutive failed evaluations, or the daily limit.
