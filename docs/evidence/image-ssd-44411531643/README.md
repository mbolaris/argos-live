# Image from `main` 44411531643 (November 18, 2026)

ISO `argos-live-amd64.iso`, 4,177,526,784 bytes, SHA-256
`702c8bd6781388ab4e4127d48df18af24098e5806d2a936861408491a4724ae0`, built by
[run 44411531643](https://github.com/mbolaris/argos-live/actions/runs/44411531643) from `main` at
`5ff3ee6` (PR #205 merged). The artifact expires after three days; a checksum-verified copy is on
Yugo in `work/toronado-iso-44411531643/`.

This image now runs on Toronado. It was written and booted on November 18 with the owner's
approval. Physical acceptance passed, and the Proctor practice exam on the 27B completed 6/6; see
[TORONADO-ACCEPTANCE.md](TORONADO-ACCEPTANCE.md). A reboot check on hardware is still open.

## What is new compared with what Toronado runs

The SSD currently runs a hand-patched local variant of the November 15 branch image `edd5893`.

- **Built from `main`; no hand edit.** This is the first CI image that finds encrypted persistence
  on a USB SSD reporting `removable=0`. The initrd fix is part of the build
  ([USB-SSD-PERSISTENCE.md](../../USB-SSD-PERSISTENCE.md)). The only device-specific step left for
  a write is the MBR entry for the existing persistence partition.
- **Runtime from `main`:**
  - each OpenClaw version gets its own Proctor profile, so the stale 2026.10.x campaign profile no
    longer blocks campaigns;
  - an owner-only campaign failure log;
  - MMLU and GSM8K benchmark packs;
  - Shakedown sidecars and the readiness ledger;
  - owner-recovery diagnostics.
- **Debian 20261118:** the LightDM and OpenEXR security updates. Otherwise the packages match
  November 15, and they are identical to candidate 44387538607.
- **Unchanged:** OpenClaw 2026.11.3, Ollama 0.40.12, Node 26.12.1, NVIDIA 550.163.01-2, kernel
  6.12.117, the `usb-storage.quirks=0bda:9201:u` UAS fix.

## Results

| Check | Result | File |
| --- | --- | --- |
| Build, checksum, credential scan | passed | [build-report.json](build-report.json) |
| Built initrd's `removable_dev()` on mock sysfs | passed | [usb-persistence.json](usb-persistence.json) |
| Three cold boots from an encrypted virtual USB attached `removable=0` ([run 44418473796](https://github.com/mbolaris/argos-live/actions/runs/44418473796)) | **passed**: unlock, records kept, clean RAM-environment shutdown, clean read-only fsck with no journal replay, each cycle | [fixed-usb-shutdown-44418473796.json](fixed-usb-shutdown-44418473796.json) |
| KVM managed startup, model reply, Model Lab speed and ability saved, assistant resumed | passed in both runs | |
| Bundled 0.6B Proctor practice smoke | **1 of 2**: the build run completed 5/6, signed and model-bound. The rerun ([44418490620](https://github.com/mbolaris/argos-live/actions/runs/44418490620)) ended with no tool call recorded, and the exam was abandoned | [pass](proctor-smoke-pass-44411531643.json), [fail](proctor-smoke-fail-44418490620.txt) |

Across the November 18 images this smoke passed 2 of 5 runs, and the November 15 image passed 2 of
4. The failures are the small model either submitting a malformed first answer or making no tool
call. The Proctor engine did not change between the images. The smoke is an intermittent gate on
the 0.6B model and says nothing about the 27B model on Toronado. On Toronado, the 27B model
completed the practice exam 6/6 in one run on November 18
([TORONADO-ACCEPTANCE.md](TORONADO-ACCEPTANCE.md)).

## Before writing it to Toronado

The pre-write checklist in [the candidate's evidence](../image-ssd-44387538607/README.md#before-writing-it-to-toronado)
applies unchanged. In short:

1. The ISO ends 9.2 MiB before Toronado's persistence partition (byte 4,187,160,576).
2. Take a fresh records backup.
3. Run offline identity and layout checks, then a rehearsed writer that adds only the MBR partition
   entry.
4. Get the owner's approval for the write and for the reboot.
5. Do the physical acceptance: UEFI boot, the encrypted overlay as root, paired SSH, NVIDIA and 27B
   inference, a saved conversation across a reboot, then a runtime health check and a Proctor
   practice exam on the 27B model.
