# Image candidate 44387538607 (November 18, 2026)

ISO `argos-live-amd64.iso`, 4,177,526,784 bytes, SHA-256
`5794b02a1369d1bf7d308c8da28c5f181f5b0f7126395b4130ec1107f92a7a9e`, built by
[run 44387538607](https://github.com/mbolaris/argos-live/actions/runs/44387538607) from
`86e6cd3` on branch `claude/image-fixed-usb-persistence` (PR #205, based on `main` at `6404f00`).
The artifact expires after three days; a verified copy is on Yugo in
`work/toronado-iso-44387538607/`.

**This is a candidate, not an accepted image.** It has not booted on Toronado. It was built from the
PR branch; per the runbook, the image written to Toronado should be rebuilt from `main` after the
PR merges.

## What it changes compared with what Toronado runs

Toronado runs a local, hand-patched variant of CI run 43734658440 (`edd5893`, November 15).

| Area | November 15 variant | This candidate |
| --- | --- | --- |
| Fixed-USB persistence | initrd edited by hand after CI | built in (`005-fixed-usb-persistence.hook.chroot`); the CI ISO itself boots USB SSDs with persistence |
| Argos runtime | `c6886130e` tree (unmerged branch) | `main` at `6404f00` plus this PR: OpenClaw-version Proctor profiles (removes the stale-profile campaign blocker), owner-only campaign failure log, MMLU and GSM8K packs, sidecars, readiness ledger, recovery diagnostics |
| OpenClaw / Ollama / Node / NVIDIA | 2026.11.3 / 0.40.12 / 26.12.1 / 550.163.01-2 | unchanged |
| Debian | snapshot 20261114 | 20261118: 3 of 1044 packages changed (LightDM and OpenEXR security updates); kernel 6.12.117 unchanged ([package-changes.tsv](package-changes.tsv)) |

## Results

| Check | Result | File |
| --- | --- | --- |
| Build, checksum, credential scan | passed | [build-report.json](build-report.json) |
| Built initrd's `removable_dev()` on mock sysfs | passed: fixed and removable USB accepted, internal disks refused, ordinary mode unchanged | [usb-persistence.json](usb-persistence.json) |
| Three cold boots from an encrypted virtual USB attached `removable=0` ([run 44394680790](https://github.com/mbolaris/argos-live/actions/runs/44394680790)) | **passed**: each boot unlocked, kept records, shut down through the RAM environment, clean read-only fsck with no journal replay | [fixed-usb-shutdown-44394680790.json](fixed-usb-shutdown-44394680790.json) |
| KVM managed startup, Model Lab speed and ability saved, assistant resumed | passed in all three runs | |
| Real bundled-model (Qwen3 0.6B) Proctor practice smoke | **1 of 3 passed** (5/6 correct, signed, model identity bound). Two runs failed with the first answer rejected as `INVALID_ANSWER_FORMAT`, then the exam was abandoned | [pass](proctor-smoke-pass-44394675364.json), [fail 1](proctor-smoke-fail-44387538607.txt), [fail 2](proctor-smoke-fail-44395765893.txt) |

The Proctor failure is not new. The November 15 image passed 2 of 4 runs of the same smoke
(43734658440 and 43736578900 passed; 43732582250 and 43734569886 failed), and both failures had this
exact signature. The Proctor engine and practice loop did not change between the two images. Treat
this smoke as an intermittent gate on the 0.6B model, not as evidence about the 27B model Toronado
uses. Diagnosis work is on `codex/proctor-practice-diagnostics`.

## Before writing it to Toronado

- Rebuild from `main` after PR #205 merges, and repeat the fixed-USB shutdown test on that ISO.
- The write still needs the device-specific MBR entry for the persistence partition. Toronado's
  partition 3 starts at byte 4,187,160,576. This ISO ends 9,633,792 bytes (9.2 MiB) before that; the
  November 15 image left 13.1 MiB. A future image that grows by about 9 MiB will not fit without
  moving the partition.
- Fresh records backup, offline identity and layout checks, a rehearsed writer, and the owner's
  approval for the specific write and reboot.
- Physical acceptance: UEFI boot, persistence unlock with the encrypted overlay as root, paired SSH,
  NVIDIA load and 27B inference, saved conversation across a reboot.
