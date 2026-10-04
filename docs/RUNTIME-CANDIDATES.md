# Stable runtime candidates

The daily upstream check discovers official stable OpenClaw/Ollama releases and
the latest Node patch in the accepted major. Discovery does not change accepted
pins or an installed system. Debian security snapshots and driver updates require
their own signed package resolution and manifest review.

Run **Prepare stable runtime candidate** manually to generate public candidate
files in a disposable hosted checkout. It requires a fresh discovery report that
matches every current pin, validates stable versions and artifact identities,
rejects downgrades/Node major changes/unrelated base updates, and checks official
release URLs. The candidate output directory is never reused.

The runner uses checksum-pinned candidate Node to regenerate the npm lock with
scripts disabled. It checks the published OpenClaw archive against SHA512 before
rebuilding bundled plugin/skill metadata, and attaches a bounded npm audit report.
This inventory does not activate addons or establish functional readiness. Audit
findings need exposure review and supported fixes; a report alone is not a pass.

The seven-day artifact contains `versions.env`, the synchronized backend pin,
`package-lock.json`, `addons.json`, `npm-audit.json` and `candidate.json`. No owner
configurations, profiles, credentials or model data are read. The workflow has
read-only repository permissions and makes no commit, PR, USB or release changes.

Review these files in a candidate branch. Run all unit/process tests, exact host
schema/recovery/addon registration checks, real pinned model/onboarding checks,
a clean ISO build and offline VM acceptance. Physical GPU, encrypted persistence
and owner-personality acceptance remain release gates. Promote through a PR and
delete the landed branch; retain the previous accepted artifact for rollback.
Automatic creation of this reviewed PR is the next C5b step.
