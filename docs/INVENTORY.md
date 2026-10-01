# Toronado inventory — October 1, 2026

Read-only inventory from the actual local Windows execution session:

- Computer TORONADO; Threadripper 3970X, 32 cores / 64 logical processors.
- ASUS ROG STRIX TRX40-E GAMING; 137,312,251,904 bytes physical memory.
- RTX 3090, 24,576 MiB VRAM, Windows driver 610.88, 275 W power limit. Unchanged.
- Windows build 26200, 25H2. Secure Boot registry reports enabled; direct firmware query needs elevation.
- Windows token is not elevated; administrator membership is deny-only under UAC.
- Ubuntu-26.04 WSL2 available; Linux 6.18.33.2-microsoft-standard-WSL2. Root execution available through `wsl -u root`. `/dev/kvm` exists; guest boot remains to be tested.
- No native QEMU, VirtualBox, VMware, or Hyper-V VM management service detected by the initial probes.
- C: has approximately 1.42 TB free; E: DATA has approximately 1.46 TB free. No model storage on either has been authorized.

## Internal disks — never USB targets

Both are Sabrent Rocket Q4 NVMe, 2,000,398,934,016 bytes:

| Serial | Current disk | Partitions |
|---|---|---|
| 6479_A743_6020_02B7. | 0 | EFI, MSR, C:, recovery; boot/system |
| 6479_A739_F161_362E. | 1 | MSR, F: (428.6 GB), recovery, E: (1.57 TB) |

F: has no recognized filesystem in the current volume probe. No format attempt was made. Its connection is NVMe, so the historical F: USB report does not identify today's USB.

## USB candidate — erase permission pending

Kingston DataTraveler 3.0, USB, 31,474,057,216 bytes (29.31 GiB); current disk 2.
Storage serial `0B8F640168E7`. PnP instance contains `08606E694934BF418705FC70`.
Windows UniqueId: `USBSTOR\DISK&VEN_KINGSTON&PROD_DATATRAVELER_3.0&REV_PMAP\08606E694934BF418705FC70&0:Toronado`.
These two serial representations differ; capture and compare both before writing.

GPT partition layout:

| Partition | Letter | Type | Offset bytes | Size bytes |
|---|---|---|---|---|
| 1 | D | Basic | 32,768 | 6,109,091,840 |
| 2 | none | System | 6,109,124,608 | 5,191,680 |
| 3 | G | Basic | 6,114,316,288 | 307,200 |

Online, not read-only, not boot/system. Windows reports Removable Media, consistent with the USB-only persistence policy. Get-Disk's exact capacity is used for target matching; Win32_DiskDrive reports a slightly smaller geometry-rounded size. This layout suggests an earlier hybrid image. It does not establish the cause of a historical formatting failure. Never run a formatting probe to diagnose it without authorization.

Writing the final full-disk image erases all partitions and files on this USB. Identity must be rechecked immediately before opening the physical device for writing. No erasure has been authorized yet.
