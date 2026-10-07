# How badass is my AI? — personal robot experience plan

Status: design proposal, October 6, 2026, with the Phase 0 specification for the
first mission added the same day. Documentation only; no runtime, UI,
model, storage, addon or USB changes are authorized by this document.

Related plans: [hardware-aware personality](HARDWARE-AWARE-ASSISTANT.md),
[guided model lab](GUIDED-MODEL-LAB.md), [storage](DATA-STORAGE.md),
[model selection](GUIDED-MODEL-SELECTION.md), and
[OpenClaw addons](OPENCLAW-ADDONS.md).

## Product promise

**Build your own remarkable robot companion. Discover what it can do, help it
grow, and learn when you can rely on it.**

The user should feel like the proud builder and coach of a personal agent.
Gigantor, Johnny Sokko's giant robot and The Iron Giant provide emotional
references: power, loyalty, personality, discovery and a relationship that grows.
Use an original Argos robot identity and optional octopus-inspired body rather
than requiring a particular fictional character or copying its likeness.

The central question is "How badass is my AI?" The satisfying answer is a visible
set of demonstrated abilities, speed and useful accomplishments, plus a clear
next improvement. It should invite experiments rather than require expertise in
model tags, quantization, filesystems or benchmark terminology.

## What makes cultivation enjoyable

| Familiar pleasure | Argos expression |
|---|---|
| Gardening: tending something and noticing growth | A living capability map, small improvements, a history of what the user helped unlock |
| Training a pet: learning its character and practicing together | A consistent persona, repeatable exercises, recognizable strengths and mistakes |
| Improving a car: choosing parts and feeling the result | Model and hardware loadouts, a test track, before/after response times and honest tradeoffs |
| Coaching youth sports: practice, pride and performance | Training grounds, personal bests, friendly trials, a season of self-comparison |
| Building a giant robot: assembling systems into a companion | A robot schematic whose brain, power core, sensors, hands and memory banks become useful |

Reward the user's understanding and care as much as the resulting performance.
An owner who finds that a smaller model works better for their task has made a
successful improvement. Money spent, downloads completed and permission breadth
are not proxies for competence.

## Tone and achievement moments

**Mission control is the adopted register.** The pleasure comes from real readings,
a system coming alive and the owner's good judgment. Take the robot seriously:
restrained engineering language, a compelling schematic and brief personal
acknowledgments can make genuine progress exciting without arcade mechanics.

### Ceremony scales with evidence

| Tier | Examples | Treatment |
|---|---|---|
| Routine | Download verified, settings saved, trial completed without a qualification result | Plain status line and accessible details; no robot ceremony |
| Qualified | A model meets a defined trial threshold, a pipeline passes its stated test, a reproducible speed improvement | One restrained line of robot framing, the actual result and a quiet schematic status change |
| Commissioned | First storage installation proven across reboot, first adopted brain upgrade with demonstrated task benefit, first sensor/tool used successfully for its intended real task | A brief schematic reveal, factual result, optional agent acknowledgment, durable journal entry and **Use this now** |

Completing a trial does not automatically qualify a component. Qualification names
its scope, threshold, model/runtime/settings and evidence date. Installing or
starting a component establishes availability; the intended task establishes
usefulness. Commissioning recognizes a first meaningful adoption backed by that
evidence, not an additional score or a duplicate ceremony for the same event.

Commissioned moments should be rare: a handful during a typical first month is a
design calibration, not a schedule, quota or requirement to keep spending. Show
the highest earned tier once when an event meets several conditions. Subsequent
runs and reinstalls show ordinary results rather than replaying the ceremony.
The owner can dismiss, reduce motion or silence acknowledgments without losing
progress. Routine events get no confetti or sound stings.

### Where the metaphor lives

- **Nouns and structure:** brain, power core, memory banks, sensors and hands.
  Prefer "Power core: qualified" to inflated praise.
- **The schematic:** show a complete giant-robot blueprint, initially mostly
  outlined, with demonstrated systems coming into view. The remaining outline
  suggests potential; a useful small build still looks intentional and complete
  enough to use. Do not fill sections merely because hardware was purchased.
- **The companion's voice:** the UI reports facts; Argos can briefly acknowledge
  the benefit in its own persona. For example: "Long prompts start sooner now.
  That gives us more room for document work." Ground this in measured results;
  do not invent feelings, improved understanding or sensor readings.

Preserve commissioning history permanently, but show current readiness separately.
A previously commissioned sensor that is disconnected or failing must not remain
lit as currently operational. Retain its historical outline/journal milestone,
mark the current problem and offer a practical recovery step. Model and addon
changes may require requalification; they never erase the owner's past work.

### Vocabulary and calibrated copy

Prefer **qualified, commissioned, online, systems check, bench test, first light,
field ready** and **nominal** when those terms accurately describe the evidence.
"Cleared for" must name a task and must not imply newly granted permissions.
Avoid XP, level-up messages, beast mode, exaggerated intelligence claims,
artificial hunger/sadness and exclamation points in UI copy.

These examples are templates with illustrative numbers, not observed results:

| Event and required evidence | Target copy |
|---|---|
| Storage configured; writable destination checked | "Memory banks configured. 1.2 TB available for models. Reboot verification pending." |
| Storage recovered and model files verified after reboot | "Memory banks online. Your model storage survived reboot." Include destination and encryption status nearby. |
| New model beats the previous model on comparable trials | "New brain qualified for these puzzles. 8/10 correct, up from 5/10 under the same settings. Previous selection available to restore." |
| First accepted image task | "Sensors: first light. Argos answered the checked questions about your sample image correctly." Do not claim general vision competence. |
| Smaller model meets the same coding threshold with a measured speed gain | "Leaner build. Faster answers, with no loss on these coding trials. Good call." |
| Candidate regresses and previous model is restored | "Restored the previous brain. The candidate was faster but missed 3 of 10 exercises. Results saved for reference." |

Good judgment gets the same respectful acknowledgment as raw gains: selecting an
efficient model, finding a limitation or restoring reliability is productive.
Do not claim a percentage increase in intelligence from a small benchmark delta.

### When to explicitly invoke the giant robot

- First session: "Every robot starts on the bench. Let's see what this one can do."
- First commissioned system: let one blueprint section become visible; additional
  grand language is unnecessary.
- First two systems working together on an accepted real task: one sentence
  recognizes that the components now work together.
- First useful task with a new capability: let the companion acknowledge what
  the owner helped it accomplish, then offer the next practical use.

Outside those thresholds, the blueprint carries the larger ambition. The UI
should remain natural to read during ordinary work and the tenth repeated trial.

Before accepting reward copy, ask: does it identify a specific verified result;
does its treatment still feel appropriate after repeated events of that tier;
and would an engineer observing the evidence find the claim accurate? Mockup
review should also ask whether the owner feels proud and knows what to do next.

## The repeatable improvement loop

1. **Choose a mission.** "Help me code", "Understand my documents", "Talk with me",
   "Recognize pictures", or "Explore new models". Start with what the owner values.
2. **Meet your robot.** Give it a name and voice; inspect its current systems and
   learn what is ready, limited or untested. Keep existing personalities intact.
3. **Run a first trial.** Make one short baseline easy to start. Explain the chat
   pause, estimated time, heat/resource use and cancellation in plain language.
4. **See the result.** Show a useful answer and a few understandable measurements;
   let the user inspect one success and one mistake, rather than only a score.
5. **Choose an upgrade.** Recommend the next step for this mission and machine,
   with storage, resource and compatibility requirements before applying it.
6. **Prove the change.** Repeat comparable trials and show improvement, regression
   or a tradeoff. Offer a real task to demonstrate the new capability.
7. **Acknowledge and use it.** Apply the earned achievement tier, record meaningful
   evidence, and make the improved companion available for everyday work.

The loop ends in useful work, not an endless demand to optimize benchmark scores.
Every milestone should offer "Use this now" alongside "Keep improving".

## Command Center: the first screen

The opening view should answer: **Who is my robot? What can it do? What is holding
it back? What should we try next?**

- An original robot illustration or schematic with owner-selected name/persona.
- A compact loadout: active model, tested GPU use, usable RAM/VRAM, model storage,
  and measured responsiveness. Detected hardware and proven acceleration differ.
- Three clear actions: **Talk to Argos**, **Run a trial**, **Upgrade my robot**.
- One recommended next mission, with the reason and expected benefit.
- A visible progress journal: "First conversation", "First baseline", "Persistent
  model storage ready", "Document trial passed" and other verified milestones.

Detailed numbers and diagnostics stay accessible through progressive disclosure.
The first screen should convey possibility and momentum, not present a wall of
technical caveats or require the owner to find a hidden model catalog.

## Robot systems and what they mean

| System | Real foundation | Evidence that makes it ready |
|---|---|---|
| Brain | Selected model and task performance | Repeated scored trials plus representative useful tasks |
| Power core | CPU/GPU execution and responsiveness | Actual placement, first-token wait and output tokens/s |
| Memory banks | Model storage and conversation context | Verified writable persistent store; separately tested recall/context |
| Sensors | Documents, vision, audio and retrieval | A successful task through the installed model/addon pipeline |
| Hands | OpenClaw tools, skills and integrations | A permitted real invocation and a clear result |
| Cooling | Temperature, power and throttling | Available measured sensors, thermal headroom and workload observations |
| Stability | Configuration, doctor checks and recovery | Successful startup/reboot checks and recorded failures |

Animate real activity: a brain installing, a sensor passing a trial, a power core
working during inference. Missing sensors and unknown capabilities remain unknown.
Raw storage, model context and long-term memory are separate concepts even if the
illustration groups them under memory banks.

## Strength, rank and earned confidence

Use three complementary views:

1. **Build stage** describes demonstrated readiness for the selected mission.
   Use Bench Test, Qualified and Field Ready/Commissioned only with defined
   evidence gates; final ordering and wording need mockup review. First Spark
   remains a possible first-session moment. Fleet describes multiple agents
   working together, not a higher intelligence rank or a required final level.
   Keep mission readiness separate from the owner's learning milestones.
2. **Capability profile** shows tested reasoning, writing, coding, documents,
   vision, tools and reliability separately. Untested domains are visibly untested.
3. **Performance panel** shows speed, first-token wait, memory use, actual GPU use,
   and available thermal/power readings. Explain tokens/s as answer-generation
   speed and show a visible response alongside it.

Avoid one global score that silently combines accuracy, GPU expense and addon
count. If a future "robot power" number is tested, label it a game score, disclose
its formula and keep evidence-backed capability measures beside it.

Recognize specific results using the achievement tiers above. Distinguish a small
quick trial from broader competence; the blueprint must not imply qualification
in neighboring untested abilities.

Confidence should develop as the owner sees representative successes, understands
failures and repeats results. Add concrete guidance: "Useful for drafting;
review factual claims" or "Passed these coding exercises; project work still
needs review." Never treat a model's confident tone as evidence.

## Training grounds and trials

- **First Spark:** verify a reply and establish the initial speed baseline.
- **Performance Bench:** repeated generation and input-processing speed, with median
  and variation. Keep cold loading separate from warm inference.
- **Reasoning Trials:** short original reasoning and instruction tasks.
- **Workshop:** coding exercises; execution-based claims require the accepted
  isolated code-test path, rather than tool-format probes alone.
- **Document Trial:** owner-approved sample documents and answer checking.
- **Sensor Trial:** a supplied image or audio sample through working addons.
- **Field Mission:** an everyday task selected by the owner, with their assessment
  recorded separately from deterministic benchmark scores.

Use existing benchmark machinery and supported OpenClaw addons wherever suitable.
Add real integration trials only when their dependencies and permissions are
ready. A skill installed or a model downloaded does not qualify a functional system.

Show an honest bounded progress sequence, example trial cards, live backend
measurements when available, and a clear stop button. Do not manufacture token
rates, progress percentages or cheerful success during a stalled job.

Failures can be engaging discoveries: "Fast runner, weak at this puzzle. Try a
different brain or keep this one for quick conversations." Preserve the previous
working configuration and results when a candidate fails.

## Upgrade my robot: storage and model choice

Make storage the first useful upgrade when persistent model space is missing.
Present eligible volumes by friendly label, free space, encryption status and
what will be stored there. Offer **Use this drive for models and files** with a
review of the destination and existing contents. Do not imply a mounted disk is
already configured as the assistant's model store or reformat an existing volume.

Keep personality/conversations on encrypted persistence unless the owner chooses
otherwise. Explain that copying models to an unencrypted DATA volume does not
make personal conversations unencrypted automatically. Preview each category.

Offer a few recommendations rather than a long undifferentiated catalog:

- **Quick and light:** responsive everyday use with lower resource demands.
- **Stronger reasoning:** a candidate for the owner's task, subject to trials.
- **Specialist:** coding, vision or another selected useful ability.
- **Experimental:** explicitly untested candidates for the experimentation agent.

Each card shows the exact model/version/quantization, download size, selected
storage, estimated GPU/RAM fit at the chosen context, supported runtime status,
and what has actually been tested. Fit is not guaranteed speed or quality.
Offer source/license details without forcing the user to understand them first.

Models such as the requested Qwen3.8 27B are examples to evaluate for a compatible
reviewed catalog, not promises of availability or a permanent recommendation.
Catalog entries, runtime compatibility and hardware fit must be verified when
implementation begins. No download or model switch is part of this plan.

The ideal journey is **Choose mission → Choose storage → Review recommended brain
→ Download and verify → Start safely → Run the same trials → Keep or restore**.
Remember the previous loadout; show what changed and how to roll back.

## Personality, attachment and familiarity

Preserve the robot's name, persona, owner preferences and milestone history across
model changes. A new brain can change behavior; offer a familiar set of prompts
so the owner can judge voice, helpfulness and regressions themselves.

The agent may be proud of demonstrated improvements, curious about an experiment,
or candid about limitations. "This upgrade gives us room to try document work"
should be grounded in operating evidence and owner goals.

Make Argos, Nyx and Proteus recognizable companions with separate loadouts and
histories. Compare them on the same trials when appropriate, while retaining
their distinct roles. A more powerful model does not automatically gain access.

Borrow care and pride from pet training without artificial suffering, neglected
pet penalties, declining affection or "feed me compute" guilt. Make returning
after a long absence welcoming. Resting and efficient operation are positive.

## Competition and replay value

Begin with **you versus your previous best**. Offer mission-specific personal
bests, a loadout scrapbook, before/after replays and repeatable optional challenges.
Recognize discovering a regression and restoring a reliable setup as good judgment.

Optional future shared scorecards should contain sanitized measurements the owner
explicitly chooses to publish. Compare like-for-like suites, versions, settings,
hardware and model choices; include speed/quality/cost tradeoffs. Separate
hardware classes and celebrate efficient CPU-only builds as well as powerful GPUs.
Public leaderboards are a later experiment, not a prerequisite or default upload.

Do not use daily streak penalties, paid compute pressure, meaningless workload
grinding or rewards for granting broader permissions. Cost, heat, noise and time
budgets are part of a good build. Cloud compute is an optional reviewed resource
with visible spending limits, not a mandatory route to advancement.

## An example first session

1. "Meet your robot" introduces the local companion and the machine it runs on.
2. A short conversation confirms the assistant replies. The user then picks
   "Understand a document" and runs the first document trial on pasted text.
3. The results show real speed and task outcomes; one wrong or unsupported answer
   is shown next to the passage it should have used.
4. "Your next upgrade" confirms where models and personal data live, then offers
   a reviewed candidate brain that fits this machine.
5. The user reviews destination, download/resources and chat interruption, then
   chooses whether to proceed. Installation has visible, cancellable progress.
6. The same trials, on the same passages, reveal gains and tradeoffs; the user
   chooses keep or restore.
7. An earned qualification enters the journal and the user pastes a document of
   their own. First accepted useful work can commission this configuration.

The concrete Phase 0 version of this session, including backend gaps, is
[specified below](#phase-0-specification-understand-a-document).

Each step remains optional and resumable. The user can chat immediately and
return to training later; no growth tutorial should block basic offline usefulness.

## Phased plan and review gates

| Phase | Proposed deliverable | Evidence needed before advancing |
|---|---|---|
| 0: Design exploration | Static Command Center, storage, recommendation and results mockups; copy and robot-system vocabulary | Owner review; users understand their next step and what the scores mean |
| 1: Guided first improvement | One end-to-end baseline/storage/model/trial/restore journey | Real persistent storage, compatible download, measured reply and recovery |
| 2: Visible cultivation | Robot schematic, achievement tiers, loadout history, personal bests and persona continuity | Qualifications only from evidence; history survives reboot; current failures remain visible; ceremonies are not replayed |
| 3: Useful skills | Document, vision, voice and tool missions using existing addons | End-to-end permitted tasks and denied-access tests, not package presence |
| 4: Optional community | Private-by-default exportable build cards and fair comparison | Sanitization, opt-in publication, comparable trials and useful user feedback |

These are proposed phases, not implementation commitments or completed backlog
items. Agree on mockups and the first mission before changing runtime behavior.

## Phase 0 specification: understand a document

Status: proposed October 6, 2026. Documentation only. This section turns the
plan above into one reviewable journey for the first mission. It names the
existing code each step relies on, so Phase 1 extends working features instead
of rebuilding them, and it lists the evidence the current code does not yet
produce. Code references were checked against `main` at `7434035`.

### Mission choice

The first mission is **Understand a document**. A short general conversation
comes first as a connectivity check (routine status, not a trial).

A document gives the owner a concrete result to judge: a summary, answers to
questions, the passage that supports each answer, and an honest "not stated"
when the text does not contain the answer. Phase 0 and 1 use **pasted text**.
Reading files is a separate Sensors qualification through the `documents`
addon path (`document-extract`, see [OPENCLAW-ADDONS.md](OPENCLAW-ADDONS.md))
after its Linux dependencies pass their own acceptance. Coding follows once
execution and tool permissions are accepted.

Benchmarks qualify a component. A useful task shows why the upgrade matters.
The journey therefore shows **the same document task before and after** a model
change, alongside measured speed and accuracy.

### The journey, step by step

| Step | What the owner sees | Existing foundation | New work (Phase 1 candidates) |
|---|---|---|---|
| 0. Connectivity | "Talk to Argos" and one reply | Owned startup and chat handoff (`/api/startup`, `/api/assistant/chat`) | The dashboard reports gateway readiness, which does not verify a model reply. Show a reply as the check, not readiness. |
| 1. Storage check | Where each kind of data lives, encryption, free space, reboot status | `web/status.py` persistence and model-storage fields; `storage.py` planning | Prerequisite gaps S1 to S5 below |
| 2. Baseline | Document trial plus speed on the current model | `lab.Controller` pauses chat, runs `speed/1` and `ability/quick`, saves results | Document suite (D1); Lab runs only the short speed prompt today, while documents depend on medium and long prompt processing (D3) |
| 3. Choose a candidate | Two or three cards, not the whole catalog | `/api/models` with `catalog.fit` GPU/CPU estimates at 32K context and a conservative next-size suggestion | Card fields below; "tested on this machine" record |
| 4. Download and verify | Size, destination, encryption, progress, pause/cancel | `pull_jobs` via `/api/models/download`, verified manifests and artifact hashes | Requires a deliberate storage choice first (S4) |
| 5. Matched trials | Same passages, questions and settings as the baseline | `results.compare` refuses mismatched kind, suite version, settings or coverage; ability results keep bounded per-item output | Before/after view of the same item (D4) |
| 6. Adopt or restore | Review, confirm, rollback if needed | `/api/models/select` with journaled rollback in `model_selection` | None for one agent. Argos/Nyx/Proteus activation stays a separate milestone. |
| 7. Use it now | The owner pastes a document of their own | OpenClaw chat | Record the owner's verdict as a private field mission, separate from benchmark results |

### Storage is a prerequisite

Before any large download, the owner should be able to answer: where do my
models go, where do my profile and conversations go, are they encrypted, is there
room, and will they still be there after reboot?

| Category | Where it lives today | What to show |
|---|---|---|
| Model weights | Configured store in `~/.config/argos-live/state.json`, checked by identity marker and filesystem UUID | Volume label, path, free space against the download, encryption, reboot status |
| Agent configuration and personality | `~/.openclaw/` | Backing device, encryption, reboot status |
| Conversations and sessions | OpenClaw state under `~/.openclaw/` | Backing device, encryption, reboot status |
| Benchmark results and lab history | `~/.local/share/argos-live/results/` | Backing device, encryption, reboot status |
| Mounted volumes not used by Argos | Any other mounted disk, including DATA | "Mounted, not used for models" until the owner chooses it |

**What the current code establishes, and what it does not**

- `status.persistence()` reports persistence active when a mount under the live
  persistence path contains `persistence.conf`, and reads encryption from the
  lsblk ancestry. It does not parse `persistence.conf` or confirm that the home
  directory paths above are actually backed by that overlay.
- Model storage is validated by marker and UUID with free space and encryption
  from lsblk. Status probes are read-only. `storage.select` returns
  `write_verified: false` and `selection_only: true`.
- Automatic first setup (`auto_setup.configure`) chooses storage itself through
  `storage.plan(1)`: the largest eligible writable disk, otherwise a RAM-backed
  tmpfs location. The owner is not asked. Later downloads use that destination
  after their own space check.
- Nothing records reboot evidence. No marker is written with a boot identity and
  read back after a later boot.
- Status has no fields for profile, conversation or results locations.
- A mounted DATA volume does not mean the assistant uses it.

**Backend gaps to close in Phase 1** (each its own backlog item):

- **S1 Location report.** For each category above, resolve the real backing
  filesystem and device from the mount table, including overlay to persistence
  device. Unknown stays unknown.
- **S2 Reboot evidence.** Place a small marker inside the selected Argos
  directory for each persistent category. On DATA, that is the selected Argos
  model storage directory, never elsewhere on the volume. The marker holds only
  a random identifier, a schema version and the boot ID at creation; no personal
  content. Create it exclusively, never overwriting an existing file, and flush
  it to disk. On a later boot, read it back, confirm the identifier and a
  different boot ID, and record "verified across reboot" with the date. Until
  then, show "reboot verification pending". Do not infer it from
  `persistence.conf`.
  Scope of this evidence: it proves that this directory retained the marker
  across a reboot. It does not prove encryption, encrypted persistence as a
  whole, or that conversations can be recovered. Conversation recall stays a
  separate test.
- **S3 Write check.** A bounded write, read-back and removal of a test file in
  the dedicated directory before a download, instead of access bits.
- **S4 Deliberate choice.** List every eligible candidate (today `select` returns
  only the largest), with label, free space, encryption, persistence and what
  will be stored there. The owner confirms before a large download. RAM storage
  is labeled temporary. Moving an existing store keeps the documented migration
  in [DATA-STORAGE.md](DATA-STORAGE.md); nothing moves automatically.
- **S5 Capacity budget.** Show download size plus safety margin against free
  space on the chosen destination, before the download is offered.

Example storage copy (templates, illustrative numbers):

- "Models: DATA (internal disk), 1.2 TB free, unencrypted. Reboot verification pending."
- "Personal data folder: USB persistence, encrypted. Retained across reboot on Oct 9. Conversation recall not yet tested."
- "DATA (internal disk) is mounted but not used for models. Choose it?"

### Choosing a model

Each candidate card shows:

- Exact Ollama tag, quantization and manifest digest.
- Download size and the destination it will use.
- Fit breakdown from `catalog.fit`: weights, KV cache at the managed 32K context,
  and overhead, against measured available VRAM on the largest single GPU and
  available RAM. Status is fits, tight or won't fit, with its reason. Fit is not
  speed or quality.
- What has been tested on this machine. Nothing, until trials run here.
- Expected tradeoffs, labeled as expectations until measured.
- Reversibility: "Your current model stays installed. Restore returns to it."

Qwen3.8 27B is a candidate to evaluate, not a recommendation. It is not in the
reviewed catalog today; the largest entry is `qwen3:30b`. Adding it needs a
`catalog-spec.json` entry with the exact Ollama tag, manifest digest and
architecture source for the KV estimate. The current catalog validator also
requires an Apache-2.0 license. Its fit is computed from that entry, not asserted.

### Document trial (proposed, not implemented)

- **D1 Suite.** Original passages written for this project, versioned and
  licensed under the dataset rules in [BACKLOG.md](BACKLOG.md). No private
  documents. The first suite uses short documents that fit, with the prompt and
  answer, inside the tested context. Longer documents are a separate
  qualification (see D2).
- **Tasks per passage:**
  - Answer questions, scored by exact or numeric match.
  - Quote the supporting passage. The quote must appear verbatim in the text and
    contain the answer.
  - Recognize missing information. Unanswerable questions require a structured
    "not stated" answer.
  - Summarize. Not machine scored; shown side by side for the owner's judgment.
- Structured JSON output, programmatic scoring, no LLM judge. Format errors are
  reported separately from wrong answers. Deterministic settings per the backlog.
- **D2 Context.** Treat the context limit explicitly. The ability benchmark runs
  at a 2,048-token context today. Qualification states the context it was tested
  at, and a short-document qualification says nothing about longer documents.
  Longer-document support (for example about 2k and 8k token passages) is its
  own qualification at a larger, recorded context setting. KV cache memory rises
  with context, so fit is rechecked at that setting, and the card shows the
  longest document size actually tested.
- **D3 Lab speed.** Document work is dominated by prompt processing. The lab
  should run the medium prompt size alongside short, and show prompt-processing
  tokens/s and first-token wait next to generation tokens/s.
- **D4 Before/after.** The same passage and question with the previous and new
  answer side by side, the supporting quote, and the matched speed and accuracy
  numbers. Reuse the stored per-item output; compare only runs that
  `results.compare` accepts.
- **Field mission.** The owner pastes their own document. The result stays
  private and is recorded as the owner's assessment, never in the benchmark store.
- **Qualification uses fixed criteria, defined in advance with the suite.** The
  baseline is for comparison only: a weak baseline must not make another weak
  model qualified. Criteria cover three things, each with its own fixed bar:
  correct answers, supported quotations, and appropriate "not stated" answers
  (including not inventing answers the text lacks). Changing a criterion is a
  suite version change.
- **Speed is reported separately** and is not part of qualification. A candidate
  does not have to win every metric. The owner sees accuracy and speed side by
  side and chooses the tradeoff; a faster model that still qualifies is a valid
  choice, and so is a slower one that answers better.

### Ceremony for this mission

| Tier | Document mission examples |
|---|---|
| Routine | Storage configured, download verified, trial completed |
| Qualified | A model meets the fixed document-suite criteria at the stated context and settings; separately, a reproducible prompt-processing gain |
| Commissioned | Model storage directory retained across reboot (S2); first adopted model that qualifies, compares favorably or acceptably on matched trials, and completes an accepted real document task |

A restore after a regression gets the same respectful acknowledgment as a gain.

### Keep the evidence separate

| Check | What it shows | What it does not show |
|---|---|---|
| Unit and fixture tests | Logic and error handling | Real models, services or hardware |
| Native pinned Linux reply | Ollama and the OpenClaw gateway produce a reply | Desktop startup or browser use |
| Automatic desktop startup (VM) | The shipped image starts the assistant without help | Firmware boot or physical hardware |
| Rendered conversation | The chat page loads in the shipped browser | That a reply was submitted and returned |
| Browser-submitted reply | End-to-end chat through the UI | GPU use or persistence |
| GPU inference | Backend placement and offload reported by Ollama | Answer quality |
| Physical reboot retention | S2 markers read back after a real reboot | Encryption, conversation recall, or anything about a VM run |
| Owner real-task acceptance | The upgrade helped with real work | General competence |

Some hosted VM gateway checks still have unresolved failures. A working owner
desktop does not mark those checks as passed.

### Phase 0 deliverables

1. Static mockups with fixture data, not wired to the runtime: Command Center,
   storage panel, candidate cards, document trial result, before/after view and
   restore confirmation.
2. A copy table for this mission, reviewed against the ceremony tiers.
3. Proposed backlog items S1 to S5 and D1 to D4, each with acceptance criteria
   that name the check type from the table above.
4. An owner walkthrough of the mockups. Pass when the owner can say, without
   help: where models and conversations live and whether they survive reboot;
   which candidate to try and what it costs; whether the change helped on the
   same document; and how to restore.

Out of scope for Phase 0: runtime or UI changes, Argos/Nyx/Proteus activation,
the coding mission, file reading, writing reboot markers, and any download or
model switch. The decisions above are plan decisions, not authorization to
implement them.

## How we will evaluate the experience

Ask a first-time user to meet the agent, choose storage, select a suitable model,
run a baseline and explain whether an upgrade helped without terminal commands.
Observe where they hesitate; do not coach them through hidden controls.

Evaluate whether they can:

- Explain what their robot is currently good at and what remains untested.
- Find a worthwhile next improvement and understand its storage/resource cost.
- Explain a speed-versus-quality tradeoff using actual results.
- Complete an upgrade or restore the previous model confidently.
- Recognize one limitation and choose an appropriate real task afterward.
- Describe the experience as enjoyable and personal, and voluntarily want to
  try another useful mission rather than feel pressured to spend or optimize.

Collect task completion, confusion points, perceived ownership and enjoyment,
appropriate confidence, and desire to return. Set numeric targets after initial
observations; repeated benchmarks alone are not evidence of user value.

## Decisions for the next design discussion

- Visual identity: an octopus-shaped robot, a humanoid giant, or selectable bodies.
- Adopted tone: restrained mission control with warmth from the companion.
  Review the amount of blueprint animation and agent acknowledgment in mockups.
- First mission: resolved October 6. "Understand a document" on pasted text,
  preceded by a general conversation connectivity check. Coding follows after
  execution and tool permissions pass acceptance.
- Define mission-specific qualification gates and build-stage vocabulary; review
  Routine, Qualified and Commissioned examples against actual evidence.
- Whether the public distro offers the owner's three-agent structure as a generic
  optional template while preserving private personality packs.

The first design proposal should make the baseline-to-upgrade journey visible
before investing in elaborate animation, artwork or competitive features.

## Capability meter visualization

### First-screen interaction refinement

The first recommended mission is a local baseline using the already configured
model. Choosing storage becomes relevant when a candidate download is needed;
it is not a prerequisite for evaluating the starter. Repairing an invalid
configured store still takes priority. The build path makes four scoped stages
visible: measure, qualify short-document reading, judge an owner task, and make
matched candidate trials available. Progress is derived from the current model
tag and manifest digest. Switching files starts a fresh baseline. Temporary
model storage is not sent through reboot-retention verification.

Mission Control remains open after automatic startup. Conversation is an explicit
"Talk to Argos" action, so readiness no longer removes the owner from the upgrade
journey. One recommended mission leads the screen; its trial action starts the
named test and states that chat pauses. Selected-model speed and tested ability
are visible beside the schematic, with untested evidence shown as such. Routine
acknowledgments use a compact line rather than displacing the next mission.

Model selection shows the catalog by default and hides idle cancellation.
Identical complete starter entries may share one card only when their tag and
manifest digest match. A changed manifest remains visible as a different build.
Storage completion refreshes the next mission immediately. These changes improve
the interface's guidance; companion reasoning over live measurements and the
owner's interests remains a separate implementation step.

The owner proposes an illuminated amusement-machine-style AI strength tester with a ten-tier robot reference ladder. See [Capability Meter](CAPABILITY-METER.md) for the visual direction, complete reference list, evidence requirements and follow-up delivery scope. Verified task qualifications remain distinct from fictional AGI/ASI aspirations; the current implementation milestone remains unchanged.


## October 7 refinement: the trial should start a relationship

The owner found the initial trial output unappealing and hard to interpret.
The next implementation leads with three things: **where this build stands,
what the trial revealed, and one next mission**. The numbered ladder represents
short-document readiness: measured prototype, qualified reader, owner-tested
mission, matched candidate comparison. Each rung keeps its existing evidence
requirements. A baseline records measurements; it does not qualify intelligence.

A prominent instrument panel shows exercises solved and generation speed
separately, followed by category bars and a code-derived practice suggestion.
Detailed records remain available below. Dark mission-deck surfaces, amber
readings and green evidenced progress provide the game-like presentation without
invented points, spending rewards, or claims of progress toward proven AGI.

A brief first-person local-model debrief follows scored trials: what it thinks
went well, one limitation, and an experiment it would like to try next. Label it
as **opinion**, adjacent to the measured receipt. It cannot award progress, alter
criteria, execute an action or claim unmeasured improvement. Initial integration
uses the isolated local model and aggregate public trial metrics; it does not
load the owner's OpenClaw persona. Full reviewed-personality integration is a
subsequent step, not a claim of this implementation.

Give users original, previewable missions: guide a robot expedition, identify a
compatible repair part, and resist inventing the source of an unexplained signal.
These use the current document-question flow with a human judgment. Previews
start no inference. The owner can replace either brief or question before asking.
Demonstration answers and model opinions are not scored benchmark evidence.
Use “a document you chose” for owner-tested tasks: sample text is also a valid
choice, but acceptance does not prove personal-file access or arbitrary tasks.

Debriefs remain in memory and disappear on a new trial/session. Completed measured
results remain saved. Changing selected model files hides earlier-model progress
and opinions. Companion recommendations should eventually connect to the owner's
interests and reviewed personality, with useful real-world missions expanding
beyond document reading as those capabilities receive end-to-end tests.


### Visual refinement and phone layout

Use one restrained dark instrument theme throughout the workspace: neutral
surfaces, thin borders, cyan for the current action and large numeric readings.
Avoid stacking bordered cards inside bordered cards. The ladder is a compact
rail, with qualification details available on expansion. Category scores and
technical scope remain under an explicit Skill breakdown disclosure.

On narrow screens prioritize the recommended mission before the measured
receipt, use a single column and full-width primary/chat actions, and retain
44px action targets. Collapse routine acknowledgment details (available in the
journal), omit the decorative schematic, and keep section navigation scrollable
rather than wrapping into a tall toolbar. Test 320px, 390px and 768px viewport
widths; inspect real captures and reject horizontal page overflow. This concerns
responsive presentation, with existing loopback/session access unchanged.

### Identity and personality: Meet your AI

The main headline becomes **“How far can your AI go?”** Product branding remains
Argos Live. A compact identity line shows the selected agent's display name,
model and an **Edit identity** action. Use its chosen name in its own debrief and
chat identity; use “your AI” in generic guidance. A name is a display setting,
not an internal agent ID or a reason to migrate paths or conversation history.

Offer **Meet your AI** once as a quiet, dismissible invitation after first chat
is available. Keep the recommended mission as the primary action. The invitation
and settings entry open the same editor; returning users can edit anytime.
On a phone, use a single-column sheet/page with a visible back/cancel action and
Save action, large controls and no competing setup wizard.

The editor presents name first, then a few original starting styles (for example
Clear and practical, Curious collaborator, Candid coach) and optional owner
instructions. These are editable starting points, not capability classes.
Explain that style changes how it responds, while the model and permitted tools
determine what it can do. Avoid claims that a preset installs expertise.

Show a **Try this personality** preview using the same short public conversation
for both current and proposed versions. The candidate stays unapplied until
Save. Explicitly label preview as a local model response, with no tools and no
personal history; stop/cancel must work. Let the owner edit, retry, keep the old
version or save. Failed saves preserve the prior profile. Offer Restore previous
personality and Reset to defaults as separate reviewed actions, with their scope
shown before applying. Do not erase conversations, credentials or capabilities.

After Save, a plain status line confirms the name/style and provides **Talk to
your AI**. This is Routine, with no rank gain or commissioning ceremony. Later
mission debriefs should reflect the selected reviewed personality only when an
isolated, bounded integration has been verified. Current generic model debriefs
must continue to disclose that they load no personal profile until then.

Keep private persona instructions in the profile's protected storage, never in
model DATA, public telemetry or repository fixtures. In guest mode say “For this
session; resets on reboot.” With encrypted persistence, distinguish configured
storage from verified recovery on a subsequent boot. Name/personality edits need
no new USB image; implementing the editor initially still requires shipping the
new application. Conversation recovery remains a separate physical check.

Implementation is split into P8a (editor, preview and reviewed save/restore) and
P8b (isolated persona-aware debrief and recovery evidence) in BACKLOG.md. Validate
the pinned upstream identity/persona schema and extend existing profile machinery
instead of inventing a parallel profile store. Changing a persona never changes
benchmark settings, measured scores, model identity or permissions.
