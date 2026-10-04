# Building the pinned live image in CI

The **Pinned Debian Live ISO** workflow builds on a disposable GitHub-hosted
Ubuntu runner, manually or on `v*` tags. It does not publish a release or modify a USB.

The runner-only wrapper rejects owner/self-hosted machines, frees three fixed
preinstalled tool directories and requires 35 GiB free. It bootstraps Debian
from `versions.env` snapshots, checks the pinned npm dependency lock without
rewriting it, verifies the seed model's manifest and every blob, and calls the
existing build script. A separate isolated bootstrap keyring contains the
Debian 13 archive public key, checked against the fingerprint published by the
[Debian FTP team](https://ftp-master.debian.org/keys.html). Release signatures
remain enforced; the installed Debian keyring handles the resulting builder.

The run records commit, runtime pins, ISO size/SHA256, package-manifest hash
and runtime-lock hash. The ISO checksum is recomputed and its ISO9660 descriptor
and core package names are checked. Build logs are scanned for common credential
patterns before artifact upload, including failure logs. This is a limited pattern
check, not proof of the absence of every possible secret. The build uses only
public inputs, disables checkout credential persistence and receives no owner
exports or release credentials.

Download the candidate artifact with ISO, `SHA256SUMS`, `packages.txt` and
`build-report.json`; verify SHA256 before using it. Large already-compressed ISO
artifacts use compression level 0, as recommended by
[upload-artifact](https://github.com/actions/upload-artifact). Candidate retention
is three days; build logs remain seven days. These artifacts are development
outputs; public Drive release publishing remains C4.

A green build establishes image creation and artifact integrity. QEMU desktop,
offline starter inference/dashboard timing and screenshots are C3. Physical
NVIDIA support, USB persistence and owner personality acceptance remain separate.
Do not rewrite the owner's USB from a build-only result.

## Offline guest check

The **Offline QEMU ISO acceptance** workflow accepts a successful build run ID,
downloads that candidate and verifies its ISO SHA256 again. It boots the original
desktop kernel/initrd under CPU software emulation with no NIC or host disk. A
serial-console argument is added only to this VM launch; the ISO is unchanged.
The [Debian Live factory test user](https://live-team.pages.debian.net/live-manual/html/live-manual/customizing-run-time-behaviours.en.html)
is used only in a fresh disposable guest. No owner password or persistence is used.

The guest checks XFCE, runs existing setup with fixed public test answers, starts
the model service/dashboard, checks an authenticated status response, runs the
short real CPU speed workload and verifies its saved result. The guest can
instead use the workflow's `auto` setup mode on an O1 candidate: it
calls `argos setup --auto`, requires a try session, verifies the read-only bundled
model source and rejects copied weights in the selected writable store. Services
are still started explicitly by the test; this is not automatic desktop startup.
The default interactive mode remains compatible with the original C2 candidate.
This disposable guest process bounds generation to eight tokens and records that setting;
comparison with normal 128-token benchmark runs is refused. The first full-length
TCG attempt reached desktop/dashboard/inference but was stopped after over twenty
minutes: its observed generation rate was about 0.3 tokens/s. This is emulation
overhead, not evidence of a desktop stall or a usable hardware performance score.
Timings and a QEMU screen dump accompany the console. A private host UNIX-socket
VNC display initializes the capture path without a LAN listener. The guest's
test-only Firefox profile uses its built-in loopback Marionette driver to wait
for real hardware/capability/catalog cards and a completed refresh. Kiosk mode
hides the session URL; the test driver strips its query after the page has captured
the token. This is test-only redaction, not ordinary browser startup behavior. Source is sent
in acknowledged, hash-checked serial chunks; credentials are never printed.
Blank/placeholder screenshots fail acceptance, and the captured desktop still
requires visual review. See Mozilla's [Marionette protocol](https://firefox-source-docs.mozilla.org/remote/marionette/Protocol.html).
The disposable guest disables X screensaver/DPMS and captures the dashboard once
its native DOM is ready, before the long CPU-emulated benchmark. This avoids
QEMU's VGA placeholder after unattended display power-off; ordinary distro idle
and lock behavior is unchanged and remains a separate check.
VM timing is not physical hardware performance.
The current test starts setup/services explicitly; automatic O2 startup and actual
UEFI/GRUB selection remain C3b. Failure never authorizes a USB rewrite.

The accepted [run 37233824509](https://github.com/mbolaris/argos-live/actions/runs/37233824509)
used automatic setup on the image built by [37231442525](https://github.com/mbolaris/argos-live/actions/runs/37231442525),
ISO SHA256 `ab40929d95c0c6ff0f5a56bdd83d75aff6ab9a6e5e9c08bce3e6a9c0c2db61f5`.
It passed all guest/host gates; the 1280 × 800 native Firefox dashboard capture
was visually reviewed. Three eight-token CPU runs reported a median 0.342 tokens/s
under TCG. Dashboard readiness was 210.08 seconds from the guest test stage,
and the VM test elapsed 978.43 seconds. These measurements have explicit emulation
and timing boundaries; they do not measure a physical desktop or boot duration.
The dashboard correctly reported the assistant not ready: this test exercises
the inference service and dashboard, not the OpenClaw gateway/conversation.

The updated-pins ISO built by
[37236087580](https://github.com/mbolaris/argos-live/actions/runs/37236087580)
also passed [37238133529](https://github.com/mbolaris/argos-live/actions/runs/37238133529).
Its downloaded 4,085,645,312-byte image matched full SHA256
`cb2cd6e107ffe7bed1e1152f754b9777d7ce9609409a8f9d0acbfbc82e36a0e7`.
The actual 1280 × 800 Firefox screenshot was reviewed. Three eight-token CPU runs
reported median 0.332 tokens/s under TCG; VM elapsed time was 940.57 seconds.
This image contains OpenClaw 2026.9.8 and Ollama 0.35.1 but predates the managed
desktop launcher. The same explicit-service, direct-kernel scope applies.
