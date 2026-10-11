# Auto Climb implementation handoff

The plan is now split so implementation status and private connection details do
not make the product contract stale:

- [Stable specification and numbered acceptance gates](AUTO-CLIMB-SPEC.md).
- [Merged progress, remaining acceptance gates and worker prompt](AUTO-CLIMB-WORKER.md).
- [Current status and evidence](BACKLOG.md).

Start with the worker work order, then the stable specification. AC1–AC3 code is merged
in PR95 and PR98; this does not establish live deployment or assistant improvement.
Continue with the separately scoped live acceptance gates before extending capabilities.

Machine-specific SSH/LAN details have moved to owner-local operational notes.
They are not secrets to reconstruct from repository history. Request authorized
connection details only when live acceptance actually requires them. No credentials,
profile data, private logs or raw USB backups belong in this repository.
