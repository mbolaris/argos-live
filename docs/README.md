# Argos Live documentation

This index sorts the documents by what you are trying to do. Documents under **Design history** are
dated specifications and reviews. They record decisions and evidence from the time they were written,
and they are not descriptions of current behavior.

## Start here

- [How Argos improves itself](HOW-IMPROVEMENT-WORKS.md): Auto Climb, task-focused campaigns, verdicts
  and what you decide.
- [First-boot setup](FIRST-BOOT.md): what `argos setup --auto` configures and what it never touches.
- [Local dashboard](DASHBOARD.md): `argos dashboard` on `127.0.0.1:8765`.
- [Fresh media and guest sessions](GUEST-MODE.md): booting with or without your saved state.

## Use your assistant

- [Try a verified model](GUIDED-MODEL-SELECTION.md): baseline, download, switch, compare.
- [Guided model acquisition](GUIDED-DOWNLOADS.md) and [verified model pull jobs](MODEL-PULL-JOBS.md).
- [Model and data storage](DATA-STORAGE.md) and [model storage selection](MODEL-STORAGE.md).
- [Personality packs](PERSONALITY-PACKS.md) and [repeatable configuration transfer](PROFILE-SYNC.md).
- [OpenClaw capabilities and addons](OPENCLAW-ADDONS.md).

## Measure

- [Ability suites and scoring](ABILITY-BENCHMARK.md): quick, standard, challenge and the tool suites.
- [Speed benchmark](SPEED-BENCHMARK.md).
- [Saved results and comparisons](BENCHMARK-RESULTS.md).
- [Owner-task evaluation protocol](OWNER-TASK-EVALUATION.md): when a score says something about your work,
  and when it does not.
- [Evaluation execution boundary](EVALUATION-CONTAINMENT.md) and
  [evaluation job lifecycle](evaluation-job-lifecycle.md).
- [Proctor service](PROCTOR-SERVICE.md) and [Proctor match watch](PROCTOR-MATCH-WATCH.md).

## Improve

- [How Argos improves itself](HOW-IMPROVEMENT-WORKS.md): start here.
- [Auto Climb product contract](AUTO-CLIMB-SPEC.md).
- [OpenClaw improvement plugin](OPENCLAW-IMPROVEMENT-PLUGIN.md) and the agent's
  [improvement guide](SELF-IMPROVEMENT-GUIDE.md).
- [Hands-off standing orders](HANDS-OFF-STANDING-ORDERS.md) and [runbook](HANDS-OFF-RUNBOOK.md): running
  the loop unattended on a dedicated machine.

## Operate and recover

- [Recovery and development limits](RECOVERY.md).
- [Offline boot-menu repair](OFFLINE-BOOT-REPAIR.md).
- [Automatic SSH after owner pairing](SSH-BOOT.md).
- [Booting a USB SSD in a UAS enclosure](USB-SSD-UAS.md).
- [Private configuration export](PRIVATE-CONFIG-EXPORT.md).

## Build and release

- [Software selection and redistribution](SOFTWARE.md); exact pins live in `../versions.env`.
- [Release process](RELEASE-PROCESS.md) and [stable runtime candidates](RUNTIME-CANDIDATES.md).
- [Building the image in CI](ISO-CI.md) and the [Windows VM workflow](WINDOWS-VM.md).
- [Code sandbox foundation](CODE-SANDBOX.md) and [Ollama client foundation](OLLAMA-CLIENT.md).
- [Implementation backlog](BACKLOG.md).

## Product direction

- [Project goals](PROJECT-GOALS.md).
- [Shared foundations curriculum](FOUNDATION-CURRICULUM.md).
- [Hardware-aware assistant](HARDWARE-AWARE-ASSISTANT.md) (requirements only).
- [Shakedown design](shakedown/DESIGN.md) and [backlog](shakedown/BACKLOG.md): the next bench experience.

## Design history

These dated documents are kept as records.

- Specifications:
  - [Play session](PLAY-SESSION.md)
  - [Mission 1](PROVING-GROUND-MISSION-1.md)
  - [Curated model journey](CURATED-MODEL-JOURNEY.md)
  - [Guided model lab](GUIDED-MODEL-LAB.md)
  - [Model onboarding](MODEL-ONBOARDING.md)
  - [Model catalog proposal](MODEL-CATALOG.md)
  - [Personal robot experience](PERSONAL-ROBOT-EXPERIENCE.md)
  - [Capability meter](CAPABILITY-METER.md) and its [references](CAPABILITY-METER-REFERENCES.md)
  - [U10 assistant trial](U10-ASSISTANT-TRIAL.md)
  - [Proctor core](PROCTOR-DESIGN.md) and [Proctor integration](PROCTOR-INTEGRATION-DESIGN.md)
- Handoffs and work orders:
  - [Auto Climb handoff](AUTO-CLIMB-HANDOFF.md) and [worker](AUTO-CLIMB-WORKER.md)
  - [Proving ground handoff](PROVING-GROUND-HANDOFF.md)
  - [Worker play session](WORKER-PLAY-SESSION.md)
- Reviews and audits:
  - [Live UI review, Oct 11](LIVE-UI-REVIEW-20261011.md)
  - [Document miss audit](DOCUMENT-MISS-AUDIT.md)
  - [Auto Climb watch and recovery](AUTO-CLIMB-WATCH-RECOVERY.md)
  - Runtime audits of [Oct 4](RUNTIME-AUDIT-20261004.md) and [Oct 11](RUNTIME-AUDIT-20261011.md)
  - [Unattended acceptance ledger](UNATTENDED-ACCEPTANCE.md)
- Status snapshots:
  - [Acceptance record, Oct 3](STATUS.md)
  - [Physical boot checklist, Oct 3](PHYSICAL-BOOT-TODO.md)
  - [Toronado inventory, Oct 1](INVENTORY.md)
