# Exact-image guest reset evidence

[Workflow 39447721277](https://github.com/mbolaris/argos-live/actions/runs/39447721277)
passed against pinned build 39445005714. The ISO source and hash, actual harness
commit and receipt hashes are recorded in `evidence.json`.

Five synthetic markers round-tripped in RAM-backed profile, workspace,
conversation, results and settings directories. The first serial console
records `reboot: Restarting system` before natural QEMU exit. A second boot of
the same read-only ISO reports a different kernel boot ID and all markers
absent, then naturally powers off. Both phase receipts and the final result are
preserved here; complete serial consoles remain in the workflow artifact.

This uses the guest boot entry with the multi-user target and no writable disks.
It does not establish graphical restart, downloaded-model reset, exclusion of
attached encrypted media, firmware boot or physical-card acceptance. It runs no
benchmark and provides no model-quality or self-improvement evidence.
