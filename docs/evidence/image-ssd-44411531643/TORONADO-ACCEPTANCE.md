# Image 44411531643 on Toronado (November 18, 2026)

The image built from `main` at `5ff3ee6` ([README](README.md)) was written to Toronado's USB SSD and
booted. Physical acceptance passed, and so did the Proctor practice exam on the 27B model, its first
pass on Toronado. Each Toronado action had the owner's approval for that action.

## Write (owner-approved, from Yugo)

The write changed only the boot area. Persistence was never written.

- **Records backup first.** The encrypted records backup was taken and checked by decrypting it.
  The writer refused to run unless its hash matched the one in the owner's approval.
- **First attempt refused.** The writer refused before writing a byte: the boot area no longer
  matched what the November 15 write had left. A read-only scan
  ([toronado-esp-drift-20261118.json](toronado-esp-drift-20261118.json)) found exactly 7 differing
  sectors, all inside the 3.3 MiB EFI partition:
  - a Windows `System Volume Information` folder created 2026-11-15 21:43;
  - its FAT entries;
  - last-access dates on `BOOTX64.EFI` and `GRUBX64.EFI`.

  The ISO region, the gap before persistence and the LUKS header were unchanged. The writer was
  re-pinned to the measured state and rehearsed again, and the owner approved a retry.
- **Second attempt written** ([toronado-write-20261118.json](toronado-write-20261118.json)). It
  wrote 4,177,526,784 bytes, MBR last, then read everything back:
  - readback hash `99c7b18d…`: the CI ISO plus MBR partition entry 3 only;
  - the gap, LUKS header and an encrypted data sample were unchanged;
  - the previous boot area was saved on Yugo for rollback.

**Lesson.** Windows writes to the SSD's vfat EFI partition whenever the disk is online on a
Windows machine. Keep the SSD offline in Disk Management. Before any boot-area write, run a
read-only scan rather than assuming the last write's state still holds.

## Acceptance (read-only, over the pinned SSH helper)

Results are in [toronado-acceptance-20261118.json](toronado-acceptance-20261118.json).

| Check | Result |
| --- | --- |
| Encrypted persistence on a USB SSD with `removable=0` | **found by the image's own build-time fix**: root is the overlay with its upper directory on `/dev/mapper/sda3` (LUKS on the SSD). Before this image, the initrd had to be hand-edited |
| UAS stall fix | `usb-storage.quirks=0bda:9201:u` in `/proc/cmdline`; dmesg shows "UAS is ignored for this device"; the SSD had no resets or I/O errors |
| SSH host key | strict pin held |
| Runtime | tree `258db6c4…` (141 files), as expected for `main` |
| OpenClaw / kernel / GPU | 2026.11.3 (`847611d`) / 6.12.117 / NVIDIA 550.163.01 on the RTX 3090 |
| Records | present (4,769 files) |
| 27B inference | `qwen3.8:27b` replied as instructed in 6.1 s including load; 17.4 GB in VRAM |

ext4 replayed its journal at this mount. That journal was left by the previous image's last
shutdown. A clean shutdown on this image has passed in CI ([run 44418473796](https://github.com/mbolaris/argos-live/actions/runs/44418473796))
but has not yet been checked on Toronado; that needs the reboot check below.

## Proctor practice exam on the 27B (owner-approved)

Results are in [toronado-proctor-27b-20261118.json](toronado-proctor-27b-20261118.json). The run
followed the same procedure as CI's managed smoke:
1. stop the assistant, and confirm Ollama stopped;
2. run `argos proctor practice --json`;
3. verify the signed transcript;
4. restart the assistant.

| | |
| --- | --- |
| Model | `qwen3.8:27b`, digest `8601b280…` |
| Form | `pilot-a` (uncalibrated, practice only) |
| Outcome | **COMPLETED, 6/6**: reasoning 2/2, math 2/2, tool-call format 1/1, evidence interpretation 1/1 |
| Turns | 1 host turn, 0 start retries, 63 s |
| Transcript | `014eaf6c…`: saved, Ed25519 signature verified, bound to the model's identity and digest |
| Afterwards | assistant restarted to `ready` |

This is a six-item practice form, not a calibrated measurement, and it is one run. It is the first
time the Proctor practice exam has completed on Toronado. On CI, the bundled 0.6B model completed
it in 2 of 5 November 18 runs.

## Campaign health check (owner-approved)

Results are in [toronado-health-quick-20261118.json](toronado-health-quick-20261118.json). One
measured `quick` campaign on `qwen3.8:27b` **completed**:
- no failure code, and 2 saved evaluations, both **20/20** with zero format errors (runs
  `6553c0ce…`, `08a78b91…`);
- Argos inspected, logged and compared on its own, and every audit was verified;
- no gain was claimed (`independent_gain_verified=false`);
- 19.5 minutes, ending with Argos restarted and the model replying.

The November 18 runtime update failed this same check with `campaign-invalid-state`, because the
stale 2026.10.x campaign profile blocked it. The per-version Proctor profile in this image removes
that block, so campaigns can run on Toronado again.

## Still open

A reboot to prove clean shutdown and persistence on hardware. It needs the owner's approval; the
owner said "not now" on November 18.
