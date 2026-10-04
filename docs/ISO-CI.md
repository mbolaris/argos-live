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
