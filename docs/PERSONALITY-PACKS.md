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

`runtime/argoslive/packs.py` provides `validate_manifest(manifest)` and `inspect(path, expected_sha256=None)`. It snapshots a bounded archive into memory, returns a private inspection report/manifest and never extracts or writes target state. Reports may contain private names and notes: keep them on owner-restricted encrypted storage and out of public logs/Git. No CLI export/import or activation is implemented by P1.
