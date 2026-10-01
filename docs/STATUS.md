# Acceptance record

Milestone 1 is **in progress**, not accepted.

| Check | Evidence / state |
|---|---|
| Local hardware and disk inventory | Completed; INVENTORY.md |
| GitHub ownership / visibility | mbolaris confirmed, public selected; repository created |
| Build environment | WSL2 + dedicated Debian builder created |
| Software compatibility and pins | Primary runtime releases/checksums verified; SOFTWARE.md |
| Encrypted persistence choice | Confirmed; local unlock prompts designed |
| Build ISO + checksum | Pending build |
| Bundled tiny model | Pending artifact/license and capacity verification; no offline first-boot claim |
| USB target identified | Kingston 29.31 GiB; erasure confirmation pending |
| Physical USB written / read-back | Not performed |
| Windows full-disk USB VM boot | KVM machine creation verified; launcher implemented, guest boot pending |
| Persistence reboot test | Pending |
| OpenClaw local model conversation | Pending |
| Physical Linux GPU use | Pending; Windows GPU inventory is not proof |
| Download interruption / artifact recovery | Implemented runtime logic; integration test pending |
| Missing external storage | Missing/wrong identity and insufficient space tests pass |
| Private restoration | Milestone 2, not implemented |
| Host installation | Milestone 3, not implemented |

No internal partitions, Windows boot configuration, GPU power settings, or USB contents have been altered. Repository source is generic. Private state and model artifacts stay outside source control.

Validation: four Python tests pass (missing storage, wrong identity, space rejection, corrupted model artifact); Bash syntax checks pass. QEMU 10.2.1 successfully created a paused KVM guest under local WSL2 and exited via its monitor. This verifies acceleration availability, not guest boot.

Runtime audit found three vulnerable dependency packages inside OpenClaw's bundled npm tree: brace-expansion (high), undici (high), ip-address (moderate). `npm audit fix --package-lock-only` did not clear them. Keep these recorded as release blockers until patched compatibility is evaluated; do not declare the image production-ready. See local audit report (excluded from public source); advisories include GHSA-qhr7-859c-m2p7, GHSA-rfgv-xxqx-mfg5, GHSA-rpw4-54j3-4h4q.
