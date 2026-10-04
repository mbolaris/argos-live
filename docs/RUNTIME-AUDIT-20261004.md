# October 4 runtime candidate audit

The hosted candidate generator used exact Node 26.10.0, OpenClaw 2026.9.8 and
Ollama 0.35.1, regenerated the transitive lock with scripts disabled, and checked
the OpenClaw archive against its recorded SHA512. Its public
[artifact run](https://github.com/mbolaris/argos-live/actions/runs/37233929440)
contains the full npm audit, file SHA256 checksums and exact source/run provenance.
All seven artifact files passed local SHA256 verification before staging the pins,
lock and inert addon inventory in the candidate branch.

The candidate report lists four vulnerable packages: three high, one moderate,
zero critical. The older recorded report listed 25; the new count is not proof
that every earlier exposure has been remediated. All four currently reported
paths are under `node_modules/npm/node_modules/`. The verified upstream OpenClaw
package declares npm 11.20.0. The refreshed lock also updates the supported Hono,
top-level ip-address and Node type packages; no forced overrides were applied.

| npm dependency | Installed | Report severity | Exposure to review |
|---|---|---|---|
| brace-expansion | 5.0.9 | High | Untrusted patterns reaching npm's glob handling can exhaust CPU/stack. See the [nested-brace advisory](https://github.com/advisories/GHSA-qhr7-859c-m2p7); the audit contains two additional related advisories. |
| http-cache-semantics | 4.2.0 | High | npm's HTTP cache handling may reuse responses across users when vulnerable stale-cache behavior is exercised. See the [cache advisory](https://github.com/advisories/GHSA-ch52-4w7c-c8xp). |
| ip-address | 10.5.0 | Moderate | npm dependency address/subnet classification can admit addresses outside an intended network boundary. See the [family-mismatch advisory](https://github.com/advisories/GHSA-j6r3-76f7-8jcv); the audit includes link-local, NAT64 and parse-size cases. |
| undici | 6.28.0 | High | npm's transport dependency has peer-controlled WebSocket failure and response handling risks. See the [WebSocket advisory](https://github.com/advisories/GHSA-rfgv-xxqx-mfg5); two additional transport advisories are in the report. |

Argos configures its fresh gateway and model service on loopback and denies
shell/file/web/update tools in the conversation-only profile. Managed model
downloads use the Python/Ollama pipeline, not npm. These reduce exposed actions;
loopback binding alone does not protect outbound package-manager operations or
prove that every affected code path is unreachable. Effective per-agent denials
and the package-manager invocation paths still require functional acceptance.
Owner-selected broader policies and optional addon installation need their own
exposure review.

H2 remains open. Preserve these findings, pursue a supported upstream npm/host
fix and repeat the audit after a new lock. Do not claim a clean audit, suppress
advisories or replace bundled dependencies silently. ISO, VM, physical GPU,
encrypted persistence and advertised-addon checks remain separate release gates.
