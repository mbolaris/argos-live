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

1. Read the finished Auto Climb session: what was kept or restored, and why. Report to the owner; do
   not ask.
2. Widen the candidate pool. Candidates are hard-coded in `INSTRUCTION_CANDIDATES` in
   `runtime/argoslive/auto_climb.py` (answer-first, quote-evidence, honest-uncertainty), so a session
   ends "options exhausted" in about 25 minutes. Add the saved `AGENTS.md` edit's pieces as candidates
   (the "owner task first" rewrite and the Lessons), then deliver with the updater. This is a runtime
   change: PR, checks, merge, bundle.
3. Investigate the tool-schema suite results of 1/40 and 0/40 with 39 format errors; suspected
   measurement problem.
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
