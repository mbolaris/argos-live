# OpenClaw 2026.10.1 candidate audit

The hosted stable-runtime candidate workflow discovered OpenClaw 2026.10.1 on
October 11, 2026, verified that the npm registry version matched the signed
GitHub stable release, and verified the package SHA512 recorded in `versions.env`.
Candidate run [38184735385](https://github.com/mbolaris/argos-live/actions/runs/38184735385)
generated the lock, addon inventory, audit and checksummed provenance. All seven
artifact files passed local SHA256 verification before the lock and inventory
were staged for review.

This is an OpenClaw-only candidate. Ollama 0.35.1 and Node 26.10.0 remain pinned.
The upstream candidate workflow also discovered newer Ollama and Node releases,
but they are outside this change. OpenClaw 2026.10.1 declares Node
`>=24.16.0 <25 || >=26.1.0`, which includes the pinned Node 26.10.0. CI must
still install and test the lock using that exact accepted Node version.

## Findings

The generated npm audit reports five transitive findings: three high and two
moderate. Each path is under `node_modules/npm/node_modules/`; the audit does not
by itself prove that the affected behavior is reachable in Argos. The findings
and installed versions are:

| Package | Installed | Severity | Reported issue |
|---|---:|---|---|
| `brace-expansion` | 5.0.9 | High | Multiple uncontrolled nested-brace parsing denial-of-service advisories |
| `http-cache-semantics` | 4.2.0 | High | Cross-user stale-cache response disclosure |
| `ip-address` | 10.5.0 | Moderate | Address classification and family-mismatch checks can bypass network boundaries |
| `postcss-selector-parser` | 7.1.4 | Moderate | Quadratic selector parsing can exhaust CPU |
| `undici` | 6.28.0 | High | WebSocket and retry-response denial-of-service/splitting advisories |

The October 4 OpenClaw 2026.9.8 audit reported the same first four packages
except `postcss-selector-parser`; the 2026.10.1 audit therefore adds one
moderate finding. npm marks fixes available, but no forced dependency overrides
or blanket `npm audit fix` were applied. Review supported upstream remediation
and reachable code paths before promotion. Preserve the findings in release
evidence; do not describe this candidate as having a clean audit.

The candidate discovery also found Debian snapshots ten days old. Refresh both
signed Debian snapshots and review the resolved package-manifest diff before a
clean ISO build. This audit does not establish compatibility, image acceptance,
or an installed upgrade. The prior OpenClaw 2026.9.8 audit remains at
[RUNTIME-AUDIT-20261004.md](RUNTIME-AUDIT-20261004.md).
