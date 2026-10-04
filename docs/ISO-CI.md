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
short real CPU speed workload and verifies its saved result. This disposable
guest process bounds generation to eight tokens and records that setting;
comparison with normal 128-token benchmark runs is refused. The first full-length
TCG attempt reached desktop/dashboard/inference but was stopped after over twenty
minutes: its observed generation rate was about 0.3 tokens/s. This is emulation
overhead, not evidence of a desktop stall or a usable hardware performance score.
Timings and a QEMU screen dump accompany the console. A private host UNIX-socket
VNC display initializes the capture path without a LAN listener. The guest's
test-only Firefox profile uses its built-in loopback Marionette driver to wait
for real hardware/capability/catalog cards and a completed refresh. Kiosk mode
hides the session URL before page JavaScript removes its token. Source is sent
in acknowledged, hash-checked serial chunks; credentials are never printed.
Blank/placeholder screenshots fail acceptance, and the captured desktop still
requires visual review. See Mozilla's [Marionette protocol](https://firefox-source-docs.mozilla.org/remote/marionette/Protocol.html).
VM timing is not physical hardware performance.
The current test starts setup/services explicitly; automatic O2 startup and actual
UEFI/GRUB selection remain C3b. Failure never authorizes a USB rewrite.
