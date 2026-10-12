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

Managed, offline QEMU acceptance did **not** pass. The runs below all used the
same candidate ISO and the unchanged CPU-only, no-network setup:

| Run | Observed result |
|---|---|
| [38200442248](https://github.com/mbolaris/argos-live/actions/runs/38200442248) | Startup reached `ready`, but `/api/assistant/chat` returned HTTP 409. A follow-up showed valid loopback configuration and token fields and a ready gateway. The guest failed before opening Model Lab. |
| [38202208359](https://github.com/mbolaris/argos-live/actions/runs/38202208359) | The chat 409 cleared. The guest reached the Lab launch command and baseline-button activation, but no Lab phase or saved run was recorded. The cropped launch screenshot still showed Mission Control. |
| [38203527669](https://github.com/mbolaris/argos-live/actions/runs/38203527669) | The guest returned from the Lab launch command but failed before the Lab view was recognized. The cropped screenshot again showed Mission Control. |
| [38205119530](https://github.com/mbolaris/argos-live/actions/runs/38205119530) | Two chat 409s cleared; the guest returned from the Lab launch command, then failed with `ValueError` before a recognized Lab-view marker. No result record or active-trial screenshot was produced. The precise exception remains unconfirmed. |

The focused QEMU harness tests pass locally (31 tests, two owner-only Linux
diagnostic tests skipped on Windows). These checks validate the harness, not the
candidate's full managed Lab journey. Do not call the candidate VM-accepted or
ship it as a proven upgrade until a disposable VM run completes the visible Lab
baseline and saves both expected results. The candidate is not installed on
Toronado; no USB write, persistent profile migration, physical GPU test, or
reboot-persistence test occurred.
