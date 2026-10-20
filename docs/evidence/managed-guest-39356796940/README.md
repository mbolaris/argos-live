# Offline managed guest acceptance

Workflow: https://github.com/mbolaris/argos-live/actions/runs/39356796940
Harness source: 508fe98
Pinned ISO build: https://github.com/mbolaris/argos-live/actions/runs/39337573532
Image runtime source: 15d067a
ISO SHA-256: 2b578d7b230986ac6beb2684a6dcd8e0ec7bf8d19600755b22a6dfcd97dfcafe

The disposable offline KVM guest used the shipped RAM-only desktop entry and
Firefox dashboard. A guarded mouse click started the baseline. The guest checked
that the job completed, both run IDs existed in the benchmark listing with speed
and ability kinds, and the assistant resumed while Model Lab remained visible.
The evidence contains the two saved IDs:

- c4b8b7676acec6817c16a78814120bc6
- 848a912852978fe7a7b29bbd1c6422ca

The cropped screenshot was reviewed and shows the shipped trial UI in its ability
phase. It is a progress frame (0/20), not completion evidence. result.json records
the subsequent completed lifecycle checks. No exam score, independent gain or
production model-quality claim is made from this service acceptance run.

KVM, CPU inference and direct-kernel boot are explicitly recorded. Firmware boot,
physical-card persistence, reboot reset and browser chat replies were not tested.
No production Toronado change or quarantine release occurred.

At code source 508fe98, Linux Tests 39356801086 passed 801 tests (3 skips), syntax
and focused signal checks. Pinned compatibility 39356801080 passed the actual SDK
bridge, browser dashboard, schema/recovery, gateway lifecycle and synthetic
evaluation request protocol. Upstream stable check 39356801064 also passed.

Earlier TCG run 39351874448 failed when the gateway reached its 600-second startup
deadline while still executing startup stages. KVM run 39356007835 passed startup
but exposed the ineffective keyboard activation. Both remain failed runs; neither
is counted as acceptance. The accepted image bytes are unchanged by the later
harness, test and workflow changes.
