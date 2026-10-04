# Maintaining current stable software

Argos tracks the latest stable OpenClaw and Ollama releases, Debian stable with security/point updates, and a supported compatible Node runtime. Latest upstream, candidate and physically accepted image are three separate states. Never label a discovered release as installed or tested.

## Discovery

The GitHub Actions upstream workflow runs daily and on demand with read-only repository permissions. It compares OpenClaw's npm latest tag with its stable GitHub release, discovers stable Ollama, and checks the newest Node patch in our pinned major. It records exact integrity/checksum metadata and writes a candidate versions file and JSON report as artifacts. Missing metadata, a prerelease, or registry/release disagreement fails discovery. It never upgrades the live assistant, edits the repository, posts issues or publishes images.

An implementing agent can also run `node scripts/check-upstream.mjs work/upstream-report`. A successful discovery job means the check worked, not that the image is current or accepted. Read its changed-version list. The Debian portion reports snapshot age; it does not inspect every Debian package or certify that security fixes have shipped.

## Candidate preparation

1. Review upstream release notes, model/GPU compatibility, configuration migrations, changed permissions, plugin/skill compatibility and dependency advisories. Prefer the latest compatible supported LTS Node line; a major change is a deliberate compatibility decision. Check supported Node engines rather than simply selecting the numerically newest runtime.
2. Copy reviewed candidate runtime pins into `versions.env`. Refresh both Debian and Debian-security snapshots to recent available timestamps; use signed APT metadata and keep authentication enabled. Keep Debian stable codename fixed until a tested major upgrade. Include stable updates and security updates. Resolve kernel, firmware, browser, desktop and NVIDIA packages from those repositories; inspect the complete package-manifest diff. Driver upgrades require physical GPU acceptance. A snapshot older than seven days is a refresh reminder, not a security guarantee.
3. Regenerate the transitive OpenClaw lock with `scripts/lock-runtime.sh` in the compatible Linux runtime. Capture the npm audit and investigate findings; do not suppress advisories or silently force dependency replacements. Fetch exact pinned archives and verify their recorded digests. Include license/redistribution notices and a source commit in release evidence.
4. Build from a fresh chroot and newly resolved package lists. Never reuse stale rootfs/lock caches after a version change. `SOURCE_DATE_EPOCH` follows the selected Debian snapshot. Preserve the previous ISO and its acceptance record.

## Required acceptance before promotion

- Run repository tests, runtime smoke tests and a disposable first-boot ISO test. Verify wallpaper/welcome, offline bundled-model startup, readiness-to-conversation behavior, diagnostics and clean stopping/recovery.
- Back up a private disposable profile and verify restoration. Exercise Argos/Nyx/Proteus configuration compatibility with isolated workspaces, effective tool policies and conversation recall. An upstream schema change must not silently drop agents or credentials. Real personal profiles require private backups before activation.
- Verify the physical desktop, persistence unlock, storage identity, retained LAN SSH/logs, local GPU inference and a saved conversation through reboot. Record exact installed versions and kernel/driver/model details. VM success does not establish physical NVIDIA acceptance.
- Produce the ISO checksum, package manifest, dependency audit, source revision, version manifest and test report. Record any unresolved blocker explicitly. Promote only after required checks pass; retain known-good rollback artifacts.

Updates should normally produce a new image plus a preservation-checked USB update. Do not perform unattended in-place npm/apt upgrades under the running personal profile. Configuration, credentials and conversations stay on encrypted persistence; model files can remain on the owner-selected DATA volume. Before media writes, reidentify the device, back it up, prove persistence preservation and obtain approval for any new erasure.

## October 3, 2026 candidate

Addon acceptance is a release gate: inventory bundled and external OpenClaw plugins, pin compatible external package versions/integrity, retain Linux dependency/model-asset notices, and smoke-test every advertised capability against the candidate host. Include per-agent tool denial, offline behavior, missing-provider recovery and private rollback. See [OPENCLAW-ADDONS.md](OPENCLAW-ADDONS.md); an installed plugin or copied skill is not a passed feature test.

The physically accepted image remains OpenClaw 2026.9.7, Ollama 0.35.0 and Node 26.10.0. Official discovery found OpenClaw 2026.9.8 and Ollama 0.35.1; Node in the pinned major is unchanged. These are update candidates, not installed upgrades. Candidate build, dependency audit, profile compatibility and physical acceptance remain outstanding.

The previous build disabled the security and updates repositories. Build configuration now enables both and pins the security archive separately; this change still requires a clean candidate build and package-manifest verification. Existing ISO/USB bytes are unchanged. The previous audit's 25 findings remain unresolved until a new audit proves otherwise.

Daily discovery is implemented. Automatic candidate PR creation, automatic ISO builds and automatic promotion are not yet implemented; preparation and acceptance remain agent-driven. Repository Actions must be enabled for the daily check to run.
