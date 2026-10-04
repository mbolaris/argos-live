# Project goals

Updated October 3, 2026. The implementation backlog is [BACKLOG.md](BACKLOG.md); this document says what we are building and why.

Argos Live is a bootable Debian live distribution for playing with local agents and models. Someone should be able to boot it, chat with a local model, try other models, and get trustworthy speed and ability numbers within minutes. The owner can also bring their own agent personalities (Argos, Nyx, Proteus) to a fresh install without cloning a whole machine's configuration.

## Two product outcomes

OpenClaw capability coverage is part of both outcomes: local memory, tools, voice, media and reviewed skills need working Linux dependencies and addon acceptance, not just installed model weights. See [OPENCLAW-ADDONS.md](OPENCLAW-ADDONS.md) and backlog A1–A5.

### 1. Out-of-the-box local AI lab (public)

| Moment | Target experience |
|---|---|
| Boot | Desktop entry boots without kernel edits on UEFI hardware; NVIDIA GPU used when present, CPU otherwise. |
| First minute | Browser dashboard opens automatically. No setup questions. Hardware card shows CPU, RAM, GPU/VRAM, backend and where models are stored. |
| First chat | Bundled starter model answers locally, offline, from the read-only image. Chat uses the OpenClaw web UI. |
| Try a model | Curated catalog marks each model *fits / tight / won't fit* for this machine, shows exact download size, pulls with live progress. |
| Numbers | One click: speed benchmark (load time, time to first token, prompt and generation tokens/s, median of 3 warm runs) in under a minute; quick ability benchmark in a few minutes. Results are saved and comparable side by side. |
| Agents | A generic Argos-like assistant (a public sample personality pack) is ready to chat; the user can create their own. |
| Keep it | Persistence is optional and offered after the first experience, never as a gate. |

### 2. Portable personalities (owner first, generic tooling)

The owner's three agents move to any Argos Live install as a **personality pack**: identity/persona documents, reviewed skill definitions and a model *preference*. Live owns everything else: runtime configuration, permissions, providers and model downloads. See [MODEL-ONBOARDING.md](MODEL-ONBOARDING.md) and [PROFILE-SYNC.md](PROFILE-SYNC.md).

| Agent | Intended role | Model and access policy |
|---|---|---|
| Argos | Primary assistant and main point of contact | Broadest owner-selected access, configured and reviewed on Live |
| Nyx | Candid discussions using the owner's chosen model | Exact model preference preserved; tool access chosen independently |
| Proteus | Model experimentation | Separate workspace/state; its model changes without affecting Argos or Nyx |

The pack format, exporter, importer and the public sample packs are generic and live in this repository. The owner's actual packs, inventories and transfer receipts are private (a private repository or the owner's Google Drive) and never committed here.

## Product principles

1. **Delight first, safely.** Remove questions, not protections. Loopback-only services, gateway tokens and the conversation-only default permission stay; widening permissions is an explicit, visible choice.
2. **Measure, don't guess.** Speeds come from backend-reported timings, never character counts. Benchmarks are fixed, versioned and deterministic (temperature 0, fixed seed, thinking disabled unless the benchmark says otherwise). Unknown means "unavailable", not an estimate.
3. **Separate image, personality and model lifecycles.** The image holds software plus a small licensed starter model. Personalities and conversations live in encrypted persistence when present. Large models go on the largest suitable writable disk, with encryption status visible. Changing a model or personality never requires rewriting the USB.
4. **Current, pinned, tested.** Track stable Debian, OpenClaw, Ollama and Node; pin exact versions and hashes per image; promote only after CI and acceptance pass. Exception: the NVIDIA driver is not pinned to a specific version; it follows Debian's packaged driver for the build snapshot, recorded in the package manifest, with CPU fallback when it does not support the GPU. See [RELEASE-PROCESS.md](RELEASE-PROCESS.md).
5. **Buildable by anyone.** The ISO builds in CI from this repository; contributors and agents should not need the owner's machines for anything except physical hardware acceptance.
6. **Stdlib-first runtime.** Runtime Python uses the standard library only, so the image needs no pip installs and tests run on any Linux or Windows checkout.

## Milestones

| Milestone | Outcome | Backlog epics |
|---|---|---|
| M1 Benchmarks | `argos bench` measures speed and ability against any running Ollama; JSON results; fully unit-tested with mocks | E0, E1 |
| M2 Out-of-box lab | Questionless first boot, dashboard with hardware card, catalog, pulls, benchmarks, results; ISO built and smoke-booted in CI | E2, E3, E4, E6 |
| M3 Portable personalities | Pack format, exporter, verified import with preview and rollback; sample packs in the ISO; owner's three agents accepted on physical hardware | E5 |
| M4 Release | ISO published on Google Drive with checksums on GitHub, release checks, dependency audit resolved or documented, hardware notes | E6, E7 |

M1 and E5's format/exporter work (P1–P2) can proceed in parallel. Repository reorganization (E8) needs owner approval and does not block anything.

## Current state

Physical desktop, welcome, encrypted persistence, stable-UUID DATA mounting, retained SSH/logging, local OpenClaw conversation and NVIDIA 29/29-layer offload pass on the updated USB (see [STATUS.md](STATUS.md)). Benchmarks, the catalog, the dashboard, questionless first boot and personality import are not implemented. The owner's redacted Argos/Nyx/Proteus reference export has been received and verified privately; nothing has been activated.

References: [multi-agent routing](https://docs.openclaw.ai/concepts/multi-agent), [backup](https://docs.openclaw.ai/cli/backup), [migration](https://docs.openclaw.ai/install/migrating), [updating](https://docs.openclaw.ai/install/updating).
