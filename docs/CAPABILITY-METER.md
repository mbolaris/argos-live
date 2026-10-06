# Capability meter — the AI strength tester

Status: proposed visualization, October 6, 2026. Documentation only; no new runtime or USB change in this proposal. Related: [personal robot experience](PERSONAL-ROBOT-EXPERIENCE.md).

## Intent and appearance

Borrow the physical vocabulary of an old amusement-machine love tester: a tall illuminated column, engraved labels, a substantial instrument face, and a clear reading. Reinterpret it as an Argos bench instrument, not a joke about romance. The user should enjoy asking, "How strong is my agent now?" and seeing a measured answer change after useful upgrades.

Title: **Argos Capability Meter**. Primary action: **Run systems trial**. Secondary actions: **Inspect evidence**, **Compare loadouts**, and **Improve this system**. Use original artwork, readable labels, optional restrained needle/light animation, reduced-motion support, and text equivalents for color. No mandatory sound, confetti, or random reading. The meter is an accessible panel in Command Center, not a replacement for Model Lab.

The initial state is **Untested**, not the bottom rank. A trial can illuminate only its supported scope. Show the current selected model and manifest identity, test date, suite version, context, and hardware beside the reading. Speed has a separate dial; it does not increase a reasoning rank.

## Owner's proposed thematic ladder

Preserve the owner's numbering: Tier 10 at the base, Tier 1 at the top. Within-tier character lists are references, not ordered benchmark scores. The full supplied list is retained in [the reference proposal](CAPABILITY-METER-REFERENCES.md).

| Tier | Proposed label | Reference examples | Interpretation in the design |
|---|---|---|---|
| 10 | Non-Autonomous Chassis | Gigantor, Giant Robo, Gundam | The builder's giant-robot ambition; human-directed operation |
| 9 | Deterministic & Fixed-Reflex Automata | Unimate, clockwork automata | Repeatable bounded routines |
| 8 | Embodied Narrow AI | Spot, Mars rovers, Atlas | Sensorimotor theme; text tests cannot qualify embodiment |
| 7 | Scripted Combat Droids | Liberty Prime, ED-209 | Fictional action/automation theme; no combat tasks required |
| 6 | Expressive Automata & Companions | Baymax, K-9, Twiki | Companion personality theme, separate from measured competence |
| 5 | Awakened Synthetics & Emergent AGI | Iron Giant, Johnny 5, WALL-E | Fictional aspiration; no local consciousness or personhood certification |
| 4 | Specialized Intellectual Companions | KITT, TARS, R2-D2 | Domain expertise theme; qualify specific useful tasks instead |
| 3 | Fully Autonomous Synthetics | Data, Optimus Prime | Fictional embodied/general-intelligence aspiration |
| 2 | Strategic Networked Overlords | J.A.R.V.I.S., HAL, WOPR | Fictional coordination/strategy theme; more access is not a higher score |
| 1 | Civilizational Superintelligences | Culture Minds, Deep Thought, Multivac | Fictional horizon; no claim that Argos tests establish ASI |

These categories intentionally preserve the owner's creative proposal. They are not a scientific taxonomy or verified claims about real products or fictional canon. Several examples overlap, and autonomy, personality, physical capability and reasoning do not form one ordered quantity. Validate any real-product comparison independently before presenting it as factual product copy.

Do not equate harmful behavior, refusal removal, unlimited permissions, or independent goal formation with strength. A useful agent that follows the owner's boundaries can qualify highly on actual tasks. Character references communicate imagination, not an endorsement of the character's actions.

## A verified reading beside the fantasy

Use two distinct visual treatments in the same instrument:

- **Verified capability:** solid illuminated segments for versioned, passed task qualifications. Initially show short-document understanding, supported quotations, and recognizing absent information separately. Later add coding, tool use, vision, memory recovery, and reliability only when their own tests exist.
- **Robot horizon:** outlined thematic labels from the ten-tier ladder, explicitly marked **Fictional inspiration — not a measured intelligence scale**. Do not attach a user's verified marker to an AGI/ASI/sentience label based on today's document suite.

The actual primary reading might be: **Short documents: qualified · 2,048-token context**. Below it: **8/8 supported answers · 8/8 grounded quotations · 8/8 missing-information checks** using actual observed results, not these illustrative numbers. A separate speed dial can show prompt tokens/s, output tokens/s and first-token wait. Untested domains remain dark and labeled untested, not failed.

Eventually a single overall build-stage indicator may summarize coverage, but only after publishing a versioned rubric with fixed gates and minimum coverage per domain. Until that rubric exists, show **Overall rank: not calibrated**. A percentage of passed tests is not a percentage of intelligence. Neither educational ranks nor fictional-character equivalence follow from a short suite.

## Evidence and progression rules

1. Fixed qualification thresholds come from the suite version; a baseline supplies comparison, not the pass bar.
2. Bind every reading to exact model manifest digest and relevant software, context, settings, hardware and enabled tools. Changed weights cannot inherit a same-tag qualification. Retain historical results but mark current evidence stale or untested as appropriate.
3. Compare only compatible runs through the existing comparison validator. A repeatable speed gain is displayed as a speed gain, not a smarter-agent claim.
4. Show passed, failed, incomplete, untested and stale explicitly. Include sample counts and measured variation where available. No simulated result lights or invented global scores.
5. Routine trial completion gets a plain status. A newly passed qualification earns a quiet light change. Commissioning requires verified qualification plus accepted useful work. Repeat trials do not repeatedly award the same moment.
6. Distinguish a model test from the integrated agent. Tools, browser interaction, GPU placement, storage retention and conversation recovery require their own evidence.
7. Preserve achievements in history while the current instrument reflects regressions. Restoring a reliable model or choosing a leaner qualified model is good judgment, not lost progress.
8. No streaks, neglect penalties or pressure to buy compute. Suggest the lowest-cost useful next experiment and show its storage, time and thermal implications.

## Example interaction

The owner opens Command Center. The column says **Untested** with outlined robot ambitions. **Run systems trial** runs the existing baseline/document workflow with progress and cancellation. The completed instrument shows the actual task qualifications and independent speed measurements. **Inspect evidence** exposes questions, supported quotes, misses and recorded settings. **Improve this system** opens existing storage/model choices, then matched trials. Keeping or restoring the candidate updates the current reading without rewriting history. A useful private document task can earn a commissioned moment; its text never enters the public benchmark or achievement journal.

## Delivery and acceptance

First deliver a static instrument mockup with four fixtures: untested, qualified short-document run, incompatible/stale evidence after a model change, and a restored previous model. Owner review should establish whether it feels exciting and substantial without implying that Argos became sentient or equivalent to a fictional superintelligence.

Implementation is a follow-up to the current Command Center/USB milestone, not a reason to delay its integration fixes or silently change its release scope. Reuse existing results, qualification, journal and comparison services. Before adding overall ranks, agree the rubric and suite coverage with the owner.

Acceptance includes: no rank from hardware capacity alone; no AGI/ASI claim from local trials; no inherited qualification after digest changes; incompatible comparisons do not trigger rewards; the same event is not replayed on reload; keyboard and reduced-motion use work; actual measurements match saved evidence. A browser test and an actual screenshot review are both required for the shipped visualization.
