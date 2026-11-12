# Standing orders

Approved by the owner on November 11, 2026 ("Approve them", in answer to "Approve the standing orders as drafted?"). In force until withdrawn. Purpose: let
the test, improve, repeat cycle run on Toronado without rebuilding the Live drive and without
asking the owner for each step.

## Why

Measured from the work log between November 1 and 11:

- 17 image candidates were built and 9 boot-area writes were made to the SSD. Each write needed
  the SSD moved to Yugo, Windows approvals, the passphrase, the SSD moved back and a reboot.
  Almost all of them were to deliver changes to Python and web files, not to the operating system.
- The log records about 48 owner confirmations or approvals.
- The improvement campaign has been paused since November 8, waiting for one owner decision:
  Argos edited its own AGENTS.md outside the managed tool, the audit flagged it, and everything
  stopped.
- An Auto Climb session has to be requested each time and has three instruction ideas to try, so
  it finishes in about 25 minutes with "options exhausted".

## What I may do without asking

1. **Look.** Any read-only check on Toronado through the pinned SSH helper.
2. **Back up.** Take an encrypted records backup at any time, and always before an update or a
   campaign.
3. **Update the Argos runtime without a rebuild.** Push a runtime bundle to Toronado over pinned
   SSH when all of these hold: it was built from a commit merged to `main` whose checks passed;
   its hash matches; a snapshot of the current runtime was taken first; it replaces only the two
   Argos-owned trees (`/usr/local/lib/argos-live/argoslive` and
   `/usr/local/share/argos-live/plugins/argos-improve`); a health check passes afterwards
   (assistant ready, one short evaluation completes). If the health check fails, the previous
   runtime is restored automatically and I report it. No reboot is involved. After any reboot I
   may re-apply the same bundle.
4. **Run the loop.** Start, watch and stop evaluations and improvement campaigns on Toronado
   inside this envelope: one evaluation at a time; the campaign yields when the owner is using
   the assistant; no model downloads; only reversible instruction changes; keep or roll back
   strictly by the preset keep policy; at most 8 hours of campaign time per day.
5. **Turn an unjournaled prompt edit into an experiment.** When AGENTS.md differs from the last
   verified version: save the edit, restore the verified version, and queue the edit as a
   candidate to be tested under the keep policy like any other. This applies to the edit
   outstanding since November 8.
6. **Merge my own pull requests** when their checks pass, if they change only runtime, tests,
   scripts for testing, or documentation.
7. **Report, not ask.** One short summary when something is kept or rolled back, when a campaign
   ends, and when anything stops the loop. No "did you click" questions; I check state myself.

## What I still ask first, every time

- Any write to the SSD's boot area, any new image, any SSD repair or reinstall.
- Any reboot or power-off (these need the passphrase at Toronado anyway).
- Downloading a model, or changing the model the deployed assistant uses.
- Any change to SSH settings, keys, host-key pins, firewall, or the agent's tool permissions.
- Deleting owner data, or anything outside the two runtime trees and the agent workspace's
  managed instruction file.
- Merging a pull request that changes the image build, boot, SSH, permissions or containment.

## When the loop stops by itself

It stops, restores the last good state where it can, and reports: a storage or USB error in the
kernel log; a failed health check; `recovery_required`; two consecutive failed evaluations; the
daily time limit; or the owner pressing Stop.

## Ending these orders

The owner can withdraw or change them at any time by saying so. They do not extend to any action
not listed above.
