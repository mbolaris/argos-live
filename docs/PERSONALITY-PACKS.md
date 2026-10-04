# Personality packs: argos-pack/1

A private personality pack carries selected identity/persona documents, reviewed skill definitions and a model preference. It never restores a runtime config. Inspecting a pack does not execute its instructions, extract files, grant tools, install dependencies or activate agents. Export, staging/preview, apply/rollback and CLI wiring are separate backlog items P2–P4.

## ZIP layout and manifest

The ZIP contains exactly one root `manifest.json` and every payload listed in it, with no directory entries or extra files. All payloads are UTF-8 text. Paths use ASCII relative slash-separated segments, without traversal, empty components, drive letters, links, device names, trailing dots, case collisions or executable permission bits. The archive is at most 32 MiB, with at most 128 members, 1 MiB per file and 16 MiB expanded total. Each member must also satisfy the expansion-ratio limit: its uncompressed size cannot exceed the larger of 64 KiB or 200 times its compressed size. Encrypted ZIP members are rejected; protect the private archive using encrypted storage and authenticated transfer.

Manifest object, with no extra fields:

```json
{
  "schema": "argos-pack/1",
  "id": "sample",
  "version": "1.0",
  "created": "2026-10-03T00:00:00Z",
  "agents": [
    {
      "id": "guide",
      "name": "Guide",
      "persona_files": ["agents/guide/persona/SOUL.md"],
      "skill_files": [],
      "model_preference": {"name": "qwen3:0.6b"}
    }
  ],
  "files": [
    {"path": "agents/guide/persona/SOUL.md", "bytes": 0, "sha256": "<64 lowercase hex digits>"}
  ]
}
```

The example's byte count/digest are placeholders, not an installable pack. Pack and agent IDs are 1–64 ASCII letters/digits/underscores/hyphens, beginning with a letter or digit. Agent IDs are unique ignoring case. Version is a nonempty string of at most 64 characters. Creation time uses UTC `YYYY-MM-DDTHH:MM:SSZ`. There are 1–16 agents. Display names are nonempty strings up to 256 characters. Optional per-agent `notes` allow up to 2048 characters. Duplicate JSON keys and nonstandard JSON constants are rejected.

Every agent has at least one persona file and a possibly empty skill list. Every payload is assigned exactly once, under its own agent ID, and has a corresponding file entry with an integer byte count and SHA256. Integrity covers exact bytes, including whitespace/newlines; the manifest itself is covered by the external archive digest. Inspection checks ZIP CRCs, complete manifest coverage and payload hashes. A supplied transfer checksum must match before ZIP inspection. Without a separately verified checksum, internal consistency does not establish the sender's identity.

## Allowed documents and exclusions

Persona files are limited to `agents/<id>/persona/{AGENTS.md,SOUL.md,IDENTITY.md,USER.md}`. Skills use `agents/<id>/skills/<skill-id>/{SKILL.md,definition.json,README.txt}`. Markdown instructions are inert review material; installing a copied skill does not establish Linux compatibility or permission to execute its suggestions.

`definition.json` is a declarative object with required `name` (identifier), `description` (nonempty, up to 2048 characters) and `instructions` (string), plus optional `dependencies` (list of identifiers). No other keys are allowed. Dependency IDs are review hints, not commands, install URLs or grants. JSON skill definitions are pack metadata; P2–P4 must translate them into an explicitly supported OpenClaw skill format before activation.

Exclude credentials/private keys, memory/history/session databases, source permissions, provider/runtime configuration, channel bindings, executables/helpers, absolute source paths, model weights and media. Structural allowlists reject excluded filenames and config fields; free-form text still requires private content review. A parser cannot prove that arbitrary prose contains no credentials, private memories or embedded commands. Exporters must select/redact source content and show exclusions; inspectors must not claim semantic clearance from a passing checksum.

## Model preference resolution

Optional `model_preference` contains required `name` and optional `quantization`; it is a preference, not a provider binding or activation instruction. Name is a model reference, without URLs or absolute paths. Quantization is an identifier. A source alias may remain unresolved.

Resolve only against verified Ollama catalog/installed manifest identities and requested quantization. Preview one of: installed and matched, in catalog but needs download, or unresolved. Do not use a similar name, different quantization or cloud fallback silently. Only a target capability test establishes that the selected model works for that agent. Live owns providers, tool grants, addon dependencies and storage.

## Inspection API

`runtime/argoslive/packs.py` provides `validate_manifest(manifest)` and `inspect(path, expected_sha256=None)`. It snapshots a bounded archive into memory, returns a private inspection report/manifest and never extracts or writes target state. Reports may contain private names and notes: keep them on owner-restricted encrypted storage and out of public logs/Git. P3 provides inert staging; P4 provides reviewed activation and scoped rollback below.

## Deliberate export (P2)

From a checkout on the source machine:

```sh
python3 runtime/argos.py pack export --source /private/openclaw-home \
  --output /private/fresh-export --agent main --skill main:example
```

Use the available Python 3.11+ executable on Windows. Repeat `--agent` for explicitly selected roster IDs and `--skill agent:skill-id` for selected workspace skills. Without `--skill`, no skills are copied. The exporter supports native `agents.list` and customized `agents.entries`. It reads an explicit workspace, or the defaults workspace only for `main`; it does not guess other agent directories. When reading Windows path metadata from WSL/Linux, supply `--workspace agent=/actual/mounted/path` explicitly. Shared/global skill roots are not exported by this first implementation; select reviewed definitions placed in the corresponding workspace rather than copying arbitrary plugin folders.

Choose a fresh output directory outside the source home and workspaces, with an existing private parent on verified encrypted storage. The exporter rejects existing destinations and linked paths. It creates owner-only directories/files on Linux and restricts fresh Windows output to the current owner and SYSTEM before writing private bytes. Encryption is the caller's storage check; ACLs are not encryption.

Only allowlisted persona and explicitly selected skill-definition files enter the ZIP. Configuration, credential stores and selected source texts are read only to resolve the roster/model preference and redact known secret values. The credential scan includes `secrets.json` and direct JSON files in `credentials`; it does not certify arbitrary prose or other secret stores. Recognizable token/private-key patterns are also redacted. The private report identifies redacted files and excluded categories; no secret values are printed. Review the resulting content and skill dependencies locally.

The exporter validates the manifest and writes a private candidate, then runs full P1 inspection before publishing `personality-pack.zip` and `SHA256SUMS`. If validation fails, an incomplete private output directory/candidate may remain for inspection; it must not be transferred as a verified pack. Source files/configuration are never changed. No OpenClaw command, helper or imported instruction is executed.

## Verified staging and preview (P3)

```sh
python3 runtime/argos.py pack import /private/personality-pack.zip \
  --sha256 <verified-transfer-digest> \
  --staging-root /private/packs/staging --active-home /private/openclaw-home
```

The staging root must already exist on owner-private, verified encrypted storage. The intended Live location is `~/.local/share/argos-live/packs/staging/` on encrypted persistence. It must be outside the active OpenClaw home and known workspaces. Encryption remains a caller/storage requirement, not a claim inferred from a filesystem path. Each import creates a fresh private stage ID with `reference.zip`, `manifest.json` and `preview.json`; existing stages are rejected, and Windows ACLs/Linux private modes are applied before writing content. A failed write may leave an incomplete private stage; only a successfully returned report establishes completion.

The importer validates the pack, snapshots the same bounded bytes, rechecks the staged archive and produces file-level added/changed/unchanged/unavailable statuses. Case-colliding IDs, differently named existing agents and unreadable/linked documents are conflicts. Unselected existing files are retained; no deletion or activation is proposed. No persona or skill extraction into workspaces occurs. It never writes active config, imports permissions/memory, installs addons or calls OpenClaw.

The preview lists every selected skill as needing review. Model resolution can consume exact verified catalog/installed inventory mappings through the library API. CLI import uses the bundled verified MD1 catalog (or --catalog PATH): exact matches are shown as in catalog and needing download; unavailable preferences remain unresolved. Caller-supplied inventory is reference evidence, not physical inference readiness; a quantization mismatch remains unresolved and no replacement is chosen. Protect preview reports: agent names, file paths and preferences may be private. P4 provides target snapshots, schema validation, reviewed activation and scoped rollback below.

## Reviewed activation and rollback (P4)

`argos pack apply STAGE_ID` and `argos pack rollback SNAPSHOT_ID` are offline maintenance operations. Stop the gateway and any writers first. `--gateway-stopped` acknowledges that precondition; it does not stop or detect running services. Verify that the active home, workspaces, staging and snapshot roots are owner-private and on encrypted storage. Encryption is not inferred from their paths. Do not use the unencrypted DATA model volume for these private files.

```sh
python3 runtime/argos.py pack apply STAGE_ID \
  --active-home /private/openclaw-home \
  --staging-root /private/packs/staging \
  --snapshots-root /private/packs/snapshots \
  --reviewed-sha256 REVIEWED_PACK_DIGEST \
  --installed-inventory /private/verified-ollama-inventory.json \
  --openclaw-version DISTRO_PIN --gateway-stopped

python3 runtime/argos.py pack rollback SNAPSHOT_ID \
  --active-home /private/openclaw-home \
  --snapshots-root /private/packs/snapshots \
  --openclaw-version DISTRO_PIN --gateway-stopped
```

The installed inventory is a caller-verified JSON mapping from exact model tags to `verified: true`, `manifest_sha256` (64 lowercase hex characters), and optional `quantization`. MD1 will supply this from real model verification. This interface does not download or verify weights itself and does not establish inference readiness. Activation also requires the same model ID in Live's existing loopback Ollama provider. Unresolved, catalog-only, missing-provider, quantization-mismatched or cloud models remain pending outside the active roster; existing pending agents remain unchanged. No default model substitution occurs.

Review all selected persona prose locally. Packs with selected skills additionally require `--reviewed-skills` after reviewing every definition and its dependencies. This flag neither installs dependencies nor grants tools. Imported text never executes during migration. Each activated agent gets a separate workspace and agent directory and the minimal conversation policy; existing Live provider credentials, unrelated settings and unselected workspace files are retained. The current implementation requires the pinned native `agents.entries` schema and refuses legacy `agents.list` rather than converting it silently.

Activation rechecks the ZIP and the staged config/document baseline. Old previews without baseline hashes, or changed target files, require a fresh import and review. It creates a verified upstream native backup, saves original affected bytes and modes in a private snapshot, validates the candidate, atomically replaces documents and config, then validates the active config. A failure restores those scoped originals. Snapshot IDs and reports may contain private paths/names; keep them private. No gateway is started.

Explicit rollback verifies backup/original-file checksums and refuses to overwrite later target edits. It restores only transaction files and removes newly created directories only when empty. Other memory, sessions, credentials and later unrelated files remain. The native backup is retained for broader manual disaster recovery; restoring it is a separate reviewed action.

A power interruption can leave a `prepared` transaction and `.argos-pack.lock` in the active home. Stop and inspect all writers before removing a stale lock, then use the retained snapshot for scoped rollback; never remove an in-use lock. An interrupted or failed recovery marked `recovery-required` needs local review. This operation coordinates pack commands only, not external editors or a running gateway, and does not provide filesystem-wide atomicity across power loss.

The pinned-runtime CI smoke exercises three-agent schema validation, actual apply and scoped rollback with fictional fixtures. Inference, effective tool denials and physical reboot acceptance are separate checks; the owner's private personalities are not activated by CI.
