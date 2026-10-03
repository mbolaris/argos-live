# Project goals

Updated October 3, 2026.

Argos Live is a generic, maintained Debian live distribution with a complete OpenClaw environment and a clear first-run experience. A personal setup is an optional portable profile, installed into owner persistence rather than built into the public ISO.

## Product commitments

1. **Generic Debian base.** Boot on supported hardware, offer desktop and diagnostic entries, preserve owner-passphrase persistence, and keep internal storage optional. Hardware-specific settings, disk UUIDs and owner identities stay out of the generic image.
2. **Complete OpenClaw environment.** Include CLI, gateway, browser dashboard, agent management, local inference and the dependencies needed for supported features. Let owners configure providers, tools, skills and integrations. The initial conversation-only choice is a starting permission profile, not a permanent restriction on the distribution.
3. **Current stable software.** Track Debian stable/security updates and supported stable OpenClaw/Ollama/runtime releases. Resolve and pin exact versions and integrity hashes per image release. Test candidate updates before promotion; retain a known-good image and profile backup. Prefer supported LTS supporting runtimes where compatible. Do not turn a tested image into an unreviewed rolling install or silently update schemas under personal state.
4. **Easy customization.** Expose agent creation/model selection through OpenClaw's UI, retain clear setup/status, and provide versioned profile export, review, import and rollback. Changing a profile or model should not require rewriting the USB.
5. **Separate image, profile and model lifecycle.** The image contains software and a small licensed starter model. Agent identities, settings, credentials and history belong in encrypted persistence. Large model weights and owner-selected files can use DATA, with their encryption status visible.

## Next milestone: portable three-agent profile

| Agent | Intended role | Model and access policy |
|---|---|---|
| Argos | Primary assistant and main point of contact | Broadest owner-selected access; reproduce the working source policy |
| Nyx | Candid discussions using the owner's refusal-removed model | Preserve the exact source model and persona; choose tool access independently |
| Proteus | Model experimentation | Separate workspace/state; change its model without changing Argos or Nyx |

These are the owner's first personal preset, not a mandatory roster for every user. Each agent needs a separate workspace and agentDir/session store. Copy exact models, identities and effective permissions from the working installation; do not guess model tags or recreate personas from names. A workspace path alone is not a security boundary.

## Sync contract

The first supported workflow is a deliberate one-way sync from the chosen source installation into the USB profile. Windows is authoritative for this initial migration. Bidirectional merge is a later feature, with explicit conflict handling.

1. Locate the actual native Windows or WSL OpenClaw installation and inventory its version, agent roster, model/provider settings, workspaces, tools, skills/plugins and bindings.
2. Create and verify an upstream OpenClaw private backup outside its source directories. Treat the archive as private: native backups can contain credentials, channel identities, memories and transcripts. Keep them off the public repository and unencrypted DATA; use private storage and an authenticated encrypted transfer.
3. Restore to a fresh staging directory in encrypted USB persistence using the installed OpenClaw verifier/restore implementation. Never extract a supplied archive over the active home directory.
4. Preview the roster and path/platform changes. Rebase Windows/WSL workspace and agentDir paths to independent Linux directories. Resolve referenced model availability and platform-specific skills, plugins and commands. Review the effective global and per-agent permissions together.
5. Retain the target gateway token, loopback binding, trusted SSH identity, Argos model-storage identity and DATA mounting configuration. Copy required personal auth only through the private migration path; OAuth/device-bound credentials may need fresh authentication. History/memory migration is a separate explicit selection from settings/personas.
6. Validate the staged config against the target's installed OpenClaw schema. Back up the active profile before activation, keep sync conflicts visible, and support restoration of the previous version. Do not execute imported setup scripts as part of archive inspection.
7. Verify each agent's identity, selected model, tools, conversation and independent state. Reboot once for persistence/recall acceptance, without rewriting the USB for profile changes.

See [the export/staging workflow](PROFILE-SYNC.md) for prepared helpers and the remaining activation work.

## Current state and next physical step

Physical desktop, welcome, encrypted persistence, stable-UUID DATA mounting, retained SSH/logging, local OpenClaw conversation and NVIDIA 29/29-layer offload pass on the updated USB. The live profile currently has only the default main agent. The owner's Argos/Nyx/Proteus source is on Toronado's Windows installation; its BitLocker volume remains locked in Linux. Boot Windows to inspect/export that source rather than unlocking Windows disks from the live OS.

The installed OpenClaw 2026.9.7 supports native backup create/verify and restore to a fresh staging directory. Its Claws packaging surface is experimental and disabled by default, so it is not the foundation for the stable-profile workflow. Public online documentation can describe newer schemas; validate with the pinned installed CLI.

Known runtime dependency advisories remain a release follow-up. See PHYSICAL-BOOT-TODO.md for hardware acceptance and remaining release issues.

References: [multi-agent routing](https://docs.openclaw.ai/concepts/multi-agent), [backup](https://docs.openclaw.ai/cli/backup), [migration](https://docs.openclaw.ai/install/migrating), [updating](https://docs.openclaw.ai/install/updating).

The concrete stable-update workflow is documented in [RELEASE-PROCESS.md](RELEASE-PROCESS.md). Daily upstream discovery is implemented; candidate build and acceptance remain required before version promotion.
