# How badass is my AI? — personal robot experience plan

Status: design proposal, October 6, 2026. Documentation only; no runtime, UI,
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
2. The user picks "Help me code" and runs a short first trial.
3. The results show real speed and task outcomes; one failed exercise is explained.
4. "Your next upgrade" offers suitable model storage and a reviewed coding brain.
5. The user reviews destination, download/resources and chat interruption, then
   chooses whether to proceed. Installation has visible, cancellable progress.
6. The same trials reveal gains and tradeoffs; the user chooses keep or restore.
7. An earned qualification enters the journal and the user starts a real coding
   task. First accepted useful work can commission this configuration.

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
- First mission: general conversation, coding, or understanding a document.
- Define mission-specific qualification gates and build-stage vocabulary; review
  Routine, Qualified and Commissioned examples against actual evidence.
- Whether the public distro offers the owner's three-agent structure as a generic
  optional template while preserving private personality packs.

The first design proposal should make the baseline-to-upgrade journey visible
before investing in elaborate animation, artwork or competitive features.
