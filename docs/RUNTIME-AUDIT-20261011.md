# OpenClaw 2026.10.1 candidate audit

The hosted stable-runtime candidate workflow discovered OpenClaw 2026.10.1 on
October 11, 2026, verified that the npm registry version matched the signed
GitHub stable release, and verified the package SHA512 recorded in `versions.env`.
Candidate run [38184735385](https://github.com/mbolaris/argos-live/actions/runs/38184735385)
generated the lock, addon inventory, audit and checksummed provenance. All seven
artifact files passed local SHA256 verification before the lock and inventory
were staged for review.

This is an OpenClaw-only candidate. Ollama 0.35.1 and Node 26.10.0 remain pinned.
The upstream candidate workflow also discovered newer Ollama and Node releases,
but they are outside this change. OpenClaw 2026.10.1 declares Node
`>=24.16.0 <25 || >=26.1.0`, which includes the pinned Node 26.10.0. CI must
still install and test the lock using that exact accepted Node version.

## Findings

The generated npm audit reports five transitive findings: three high and two
moderate. Each path is under `node_modules/npm/node_modules/`; the audit does not
by itself prove that the affected behavior is reachable in Argos. The findings
and installed versions are:

| Package | Installed | Severity | Reported issue |
|---|---:|---|---|
| `brace-expansion` | 5.0.9 | High | Multiple uncontrolled nested-brace parsing denial-of-service advisories |
| `http-cache-semantics` | 4.2.0 | High | Cross-user stale-cache response disclosure |
| `ip-address` | 10.5.0 | Moderate | Address classification and family-mismatch checks can bypass network boundaries |
| `postcss-selector-parser` | 7.1.4 | Moderate | Quadratic selector parsing can exhaust CPU |
| `undici` | 6.28.0 | High | WebSocket and retry-response denial-of-service/splitting advisories |

The October 4 OpenClaw 2026.9.8 audit reported the same first four packages
except `postcss-selector-parser`; the 2026.10.1 audit therefore adds one
moderate finding. npm marks fixes available, but no forced dependency overrides
or blanket `npm audit fix` were applied. Review supported upstream remediation
and reachable code paths before promotion. Preserve the findings in release
evidence; do not describe this candidate as having a clean audit.

The candidate discovery found Debian snapshots ten days old. The candidate now
pins both repositories to `20261011T000000Z`; the candidate check observed the
Debian and Debian-security Release endpoints for that snapshot. The clean image
build completed, and its resolved package manifest and runtime pins were verified
against the build report. This audit does not establish VM acceptance or an
installed upgrade. The prior OpenClaw 2026.9.8 audit remains at
[RUNTIME-AUDIT-20261004.md](RUNTIME-AUDIT-20261004.md).

## npm advisory reachability review

Static inspection of the exact 2026.10.1 package found `npm@12.1.0` as a direct
dependency. The five audited packages are nested beneath that bundled npm. In
`dist/npm-install-env-*.mjs`, OpenClaw selects its bundled `npm/bin/npm-cli.js`
only when the JavaScript runtime is Bun; otherwise it executes the `npm` command
from `PATH`. Argos pins and launches Node 26.10.0 and does not configure Bun, so
the reviewed default Argos gateway/chat path does not select this bundled npm
tree. Explicit plugin-install and package-update flows are the relevant npm
entry points; a Bun-launched OpenClaw can select the bundled npm tree on those
flows. This is a static call-path review, not exploit testing, and does not make
the audit clean or prove every transitive package unreachable. Keep the five
findings in the release record; do not add unsupported overrides. Recheck if the
runtime changes to Bun or upstream publishes a supported dependency fix.

## Compatibility migration found during PR #99

The first pinned compatibility run failed because its legacy fixture used
`agents.entries.<id>.default: true`. OpenClaw 2026.10.1 retires that marker and
requires the old owner to be made explicit. The official migration is
`openclaw doctor --fix --non-interactive`; it preserves the prior owner in
surface-specific fields and records `agents.ownership: "explicit"`. The
candidate smoke now runs that migration only in disposable fictional state,
checks the preserved owners, validates the migrated config, and then exercises
backup/restore. Pack activation also preserves the sole implicit owner when it
expands a single-agent roster, emits no retired marker, and refuses unmigrated
legacy configs or channel rosters whose routes require Doctor's richer binding
migration. Local Windows tests and the pinned 2026.10.1 schema/recovery smoke
pass. PR #99 merged as `4fd900a119fcd43c18cc8f095223fda11dca36b3`; it updates
OpenClaw only, leaving Node 26.10.0 and Ollama 0.35.1 pinned.

This is not evidence that any persistent owner profile has been migrated. For
an upgraded preserved profile, retain its original config and state backup, run
the release's Doctor migration before starting the gateway, verify the
resulting owners and bindings, then validate the config. Do not remove
`default` markers by hand.

## Candidate image and disposable VM acceptance

The exact merged candidate built successfully in ISO workflow run
[38187784719](https://github.com/mbolaris/argos-live/actions/runs/38187784719).
The build and artifact verification checked the pinned runtime and package
manifest, and the ISO's persistent desktop default and explicit temporary guest
entry were reviewed. This confirms a built candidate, not an installed upgrade.

Hosted managed, offline QEMU acceptance did **not** pass. The runs below all used
the same candidate ISO and the unchanged CPU-only, no-network setup:

| Run | Observed result |
|---|---|
| [38200442248](https://github.com/mbolaris/argos-live/actions/runs/38200442248) | Startup reached `ready`, but `/api/assistant/chat` returned HTTP 409. A follow-up showed valid loopback configuration and token fields and a ready gateway. The guest failed before opening Model Lab. |
| [38202208359](https://github.com/mbolaris/argos-live/actions/runs/38202208359) | The chat 409 cleared. The guest reached the Lab launch command and baseline-button activation, but no Lab phase or saved run was recorded. The cropped launch screenshot still showed Mission Control. |
| [38203527669](https://github.com/mbolaris/argos-live/actions/runs/38203527669) | The guest returned from the Lab launch command but failed before the Lab view was recognized. The cropped screenshot again showed Mission Control. |
| [38205119530](https://github.com/mbolaris/argos-live/actions/runs/38205119530) | Two chat 409s cleared; the guest returned from the Lab launch command, then failed with `ValueError` before a recognized Lab-view marker. No result record or active-trial screenshot was produced. The precise exception remains unconfirmed. |
| [38208361541](https://github.com/mbolaris/argos-live/actions/runs/38208361541) | With continuous title stability inside the original launch deadline, the guest reached the visible-page and button-activation markers. The status API remained available but recorded `model-lab-baseline-not-started`; no baseline result was saved. Visual review shows a blank/loading frame at the title gate and enabled baseline controls after keyboard activation. This is a concrete browser-automation readiness/focus blocker, not a completed trial or proof that a normal user click fails. |
| [38212323579](https://github.com/mbolaris/argos-live/actions/runs/38212323579) | With the isolated native Marionette profile, startup reached `ready` and a transient chat-destination 409 recovered. The Lab launcher command returned, then the guest reported `TimeoutError` after `model-lab-automated-profile`, before the visible-control or button-click markers. Diagnostics contain only the console and launch screenshot, with no completed result. Visual review shows Mission Control in the launch capture. The exact timed-out Firefox subcommand is unconfirmed; this is not Lab acceptance or proof that a normal user click fails. |

The follow-up harness at `a20cfda` separates the launcher-command check from
browser interaction. It uses the same shipped Firefox binary in an isolated,
disposable Marionette profile, waits for the actual visible and enabled Lab
control, and is intended to send a native WebDriver element click. It does not
start the trial through an API or JavaScript click. Run
[38212323579](https://github.com/mbolaris/argos-live/actions/runs/38212323579)
failed before the visible-control and click markers. Interaction with the
original launcher tab is not claimed. No automatic repeat or timeout increase
was made before the owner resumed investigation.

The owner-resumed local WHPX run with harness `727aa22` completed successfully
against the same fully verified ISO. Safe stage markers show connection,
protocol handshake, session creation, navigation, visible enabled controls and
the native button click. The real CPU baseline completed all 20 challenges,
saved both speed and ability records, and resumed the assistant. The local
adapter uses the current guest scripts verbatim and the current host result
validator; network, host disks and the existing time budgets remain unchanged.
Cropped shipped-Firefox captures were visually reviewed, including the Lab
controls and the completed 20-response answer view. The latter was captured
while the unscored opinion was being written; it does not prove a visually
captured incremental challenge answer. This establishes scoped local baseline
acceptance, not hosted CI acceptance or an identified cause of the hosted
Firefox timeout. The original launcher tab, document mission, Auto Climb,
browser-submitted chat, physical GPU, firmware and reboot persistence remain
outside this run's evidence. The USB has not yet been written.

The downloaded ISO was independently verified in full against `SHA256SUMS` and
the build report: 4,077,649,920 bytes, SHA256
`5a31e0f019c6aae1e499b44dd1e63ac4d8efd1a8557c7d6481a382023e30e3d8`.
Its package-manifest hash, exact source commit, runtime lock and all runtime
pins match the report. Inspection of the actual ISO confirms persistent desktop
defaults in GRUB and BIOS menus and separate explicit temporary guest entries.
All three candidate EFI files match the connected Kingston and its new backup.
These file checks do not establish VM or physical acceptance.

The focused QEMU harness tests pass locally (39 tests run, two owner-only Linux
diagnostic tests skipped on Windows). These checks validate the harness, not the
candidate's full managed Lab journey. The local disposable VM run now completes
the visible Lab baseline and saves both expected results; its remaining scope
limits above still apply. The candidate is not installed on
Toronado; no USB write, persistent profile migration, physical GPU test, or
reboot-persistence test occurred.
