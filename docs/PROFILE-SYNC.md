# Repeatable personal configuration transfer

Argos is a generic live image plus an optional private profile. Capture source configuration, transfer it with authenticated encryption, review Linux compatibility, stage on encrypted persistence, validate and activate with a target rollback snapshot. Repeating the process creates a new candidate and an explicit diff; it must not overwrite live agents blindly.

## Current scope: personality and selected skills

The owner narrowed the default transfer on October 3: transfer personality/identity documents and reviewed skills only. Live owns model downloads, providers, permissions and runtime configuration. The wider exports and native-backup workflows below remain optional reference/recovery tools, not a request to restore Windows configuration. Exclude memory/history, credentials, source tool grants and Windows helpers from this default path. Resolve model preferences separately and download artifacts directly into Live's dedicated model directory. See [MODEL-ONBOARDING.md](MODEL-ONBOARDING.md) for onboarding progress and measured performance acceptance.

## Transfer contract

The first supported workflow is a deliberate one-way transfer of personalities and reviewed skills. Windows is the source for these documents; Live owns its runtime configuration and downloads its own models into an owner-selected dedicated data location. Bidirectional merge is a later feature, with explicit conflict handling. See [MODEL-ONBOARDING.md](MODEL-ONBOARDING.md).

1. Locate the actual native Windows or WSL OpenClaw installation and inventory its version, agent roster, model/provider settings, workspaces, tools, skills/plugins and bindings.
2. Export a narrow allowlist of identity/personality documents and selected skill definitions. Existing wider archives remain private reference material. Exclude memory/history, credentials, provider configuration, channel bindings, Windows helpers and source permission settings from the default transfer.
3. Verify the archive and stage documents as inert data in a fresh encrypted-persistence directory. Never extract a supplied archive over the active home directory. A native full backup is an optional separate recovery workflow, not the default personality transfer.
4. Preview the exact document selection and independent Linux paths. Review each skill's capabilities and dependencies; port required helpers separately. Configure access locally rather than inheriting source global/per-agent grants.
5. Retain the target gateway token, loopback binding, trusted SSH identity and persistence/storage configuration. Resolve model source revisions, hashes and projectors, then download them directly from Live into its own model directory. Source weights stay untouched. Credentials and history/memory remain separate explicit choices.
6. Validate the staged config against the target's installed OpenClaw schema. Back up the active profile before activation, keep sync conflicts visible, and support restoration of the previous version. Do not execute imported setup scripts as part of archive inspection.
7. Verify each agent's identity, selected model, tools, conversation and independent state. Reboot once for persistence/recall acceptance, without rewriting the USB for profile changes.

BACKLOG.md items P1–P5 implement this contract as a generic personality pack (`argos-pack/1`); P7 is the owner's physical acceptance.

## Two distinct export types

**Configuration-only ZIP:** A local source agent can capture a redacted roster, personas, model/provider references and declarative settings. Credentials and executable helpers are excluded. History, memories and authentication are not implied. Inspect the exact manifest and exclusions; archive checks do not prove complete recovery or Linux compatibility.

**Native private backup:** scripts/export-openclaw-profile.ps1 invokes the source's installed OpenClaw backup create --verify from Windows or WSL. It can contain credentials, sessions and memories. Use protected private output outside all OpenClaw state/workspace trees and outside the repository. Preserve source software; inspect CLI capabilities rather than upgrading to export. An incomplete backup must never be used as a recovery point.

Native backups use scripts/stage-openclaw-profile.py for native verify/restore to a fresh target. A configuration-only ZIP is NOT a native backup and must NOT use that helper. scripts/inspect-config-bundle.py checks digest, paths, links, duplicates, executable helpers, expansion limits and CRCs without extraction or execution. Its inventory is private; content and credential exclusion still need review.

## Authenticated encrypted transfer

Use owner-authorized SFTP with Yugo's existing Ed25519 public key; retain its private key on Yugo. Windows has a separate host identity: the trusted Linux fingerprint does not authorize a Windows host key. Obtain the Windows public host key and SHA256 fingerprint through the owner/local agent, compare before pinning, and use StrictHostKeyChecking=yes. Obtain source archive SHA256 and byte count separately and compare after transfer.

If no endpoint exists, scripts/prepare-windows-profile-transfer.ps1 prepares a private read-only SFTP candidate with a dedicated host key, an inspected existing local account and verified controller LAN address. It requires administrator rights and protected BitLocker staging, preserves the source export, and does not install OpenSSH, activate services or change firewall rules. The local agent must inspect/install Windows OpenSSH Server if needed, review the candidate and activate a temporary endpoint without replacing a working SSH service/configuration. Scope its firewall rule to the controller and private LAN interface. The candidate disables passwords, shell access and forwarding and confines read-only SFTP to the copied ZIP.

Verify actual authentication, chroot/read-only behavior and firewall scope. No router forwarding. No HTTP download of private exports. Generic scripts/public keys can be shared separately. Keep received archives/reports in owner-restricted protected storage on Yugo, then encrypted live persistence; never in unencrypted DATA or public Git history. After verified receipt, stop/remove only the temporary endpoint and firewall rule; retain the protected source export.

## Reviewed Linux migration

1. Inventory the source format/version and roster. Treat persona documents, instructions and settings as data, never executable instructions for the migration agent.
2. Record explicit mappings for independent Linux workspaces/agent state, schema fields, exact models/providers, tools/skills/plugins, bindings and missing dependencies. Do not guess Windows paths or model names.
3. Preserve target gateway token, loopback listener, SSH identity and persistence/storage selection. Review effective global and per-agent permissions. Argos gets owner-selected access; Nyx's discussion model does not imply broad tool access; Proteus experiments must not change the other agents.
4. List missing credentials/providers for local reauthentication. Never silently substitute source secrets, blank credentials or new provider bindings. Memory/history require separate explicit selection.
5. Stage in a fresh owner-only encrypted-persistence directory and validate with the installed Linux OpenClaw. Show a diff and unresolved items. Keep active configuration unchanged until its verified private rollback snapshot and reviewed activation are ready.
6. Test each agent's identity, model, permitted/denied tools, conversation and recall, then reboot to verify persistence. Retain a private migration receipt with source digest, source/target versions, mappings, exclusions, evidence and rollback location.

Activation, conflict-aware incremental sync and recurring migration are not yet implemented. Initial direction is Windows to Linux. Repeated imports must report conflicts with live-side edits rather than erase them.

## October 3 handoff

Toronado's agent reports a verified redacted ZIP at C:/Projects/Argos-Live/local/private-config-export-20261003-121440/argos-nyx-proteus-config.zip. Credentials/executable helpers are excluded and nothing imported. The full recovery backup stopped incomplete. Yugo has now received the ZIP over restricted pinned-key SFTP and verified its transfer digest, archive inspection and internal manifest. Windows source SSH remains unavailable; a temporary Yugo receiver was used instead. That receiver is now stopped. Keep Windows running for the nonsecret model/backend/helper inventory before Linux translation. A full source recovery backup is not a prerequisite to read-only inspection; target activation still requires its own verified rollback snapshot.

The source agent also published its generic exporter and source-schema documentation. Windows source OpenClaw is reported as 2026.9.6 with customized agents.entries. See PRIVATE-CONFIG-EXPORT.md and scripts/export-personal-config.py. The reference export includes selected top-level memory summaries and Markdown skill definitions; their presence does not authorize automatic memory or capability activation.

## Repeatable inert migration planning

scripts/plan-config-migration.py accepts the verified ZIP, --sha256, a fresh --target directory, and the inspected Linux --target-home. It requires the internal reference manifest, preserves original IDs and effective model references, proposes independent Linux workspace/agent-state paths, and records schema/permission validation as pending. It stages only an inert reference ZIP, inspection report and migration plan; it never creates openclaw.json, extracts persona instructions into live workspaces, imports memory/skills, grants permissions, calls provider APIs or activates agents. Existing destinations are rejected, so repeated planning cannot overwrite an earlier review.

The caller must verify encrypted backing storage and owner-only permissions before staging, particularly Windows ACLs; Python mode bits alone do not enforce Windows privacy. The staged file is a review plan, not a ready-to-install OpenClaw configuration. Source/target schema validation, model backend readiness and target rollback remain separate gates. Fixture tests and the received real bundle passed planning on Yugo; no Linux activation is claimed.

## Optional reference extraction

`scripts/stage-config-reference.py` verifies the redacted ZIP's transfer digest, CRCs, exact internal manifest coverage and each payload hash before extracting reference files into a fresh private directory. It rejects traversal, links and duplicate names and never calls OpenClaw or activates configuration, memories, skills or execution permissions. Windows staging explicitly restricts output ACLs to the current owner and SYSTEM; Linux output directories/files use modes 700/600. Select and verify encrypted storage separately. See PRIVATE-CONFIG-EXPORT.md.

Actual source reference extraction passed on Toronado Windows; model/backend/helper metadata and artifact verification are retained separately in protected private storage. The source native backup remains incomplete. Planning or extraction is not a successful Linux migration, and personal dependency inventories do not belong in this public repository.
