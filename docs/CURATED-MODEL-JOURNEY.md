# Curated models and reversible upgrades

Owner direction, October 8, 2026. Implementation specification for J3, extending
[PLAY-SESSION.md](PLAY-SESSION.md). This is not a catalog refresh or model acceptance.

## A small lineup with distinct jobs

Keep the bundled starter available without downloads. Present at most three
downloadable general-purpose choices; recommend one based on the current mission,
measured hardware and storage. Quality means local usefulness at an acceptable
cost, not parameter count, publisher scores or novelty. No profession choice is
required during the shared foundations.

Initial candidate lineup for artifact review and local evaluation:

| Role | Candidate | Reason to evaluate |
|---|---|---|
| Bundled fallback | Existing pinned `qwen3:0.6b` | Start offline and recover without downloading |
| Compact | `qwen3:4b-instruct-2507-q4_K_M` | Evaluate a compact instruction-following upgrade |
| Balanced | Existing pinned `qwen3:8b` | Evaluate useful accuracy and latency on midrange machines |
| More capacity | Existing pinned `qwen3:14b` | Evaluate accuracy gains when memory and latency allow |

These are candidates, not a universal ranking. Do not preselect a download or
promise gains. If an entry fails identity/license/runtime review or meaningful
local trials, omit it and explain the evidence; do not fill a quota. An unchanged
digest need not be refreshed just because a mutable upstream tag moved.

Move 1.7B and 30B out of the default acquisition shortlist. Keep vision, coding
and community discussion models out of the shared introductory journey; future
specialist choices require a supported mission and independent acceptance. Do
not remove installed models, delete weights or strand existing selected models,
profiles, results or pending rollback transactions. An already-reviewed legacy
identity may remain in a compatibility inventory without being recommended for
new acquisition. Distinguish that inventory from the small curated storefront.

## Identity review before promotion

On October 8 the official [Qwen3 tag listing](https://ollama.com/library/qwen3/tags)
distinguished `qwen3:4b` (short digest `359d7dd4bcda`) from the explicit
`qwen3:4b-instruct-2507-q4_K_M` (`0edcdef34593`). The current specification pairs
`qwen3:4b` with an Instruct architecture source. Audit the checked-in full manifest,
config, template and architecture identity before any refresh. Short page digests
are discovery hints only; they cannot replace verified full artifact hashes.

Use `scripts/update-catalog.py` and existing immutable architecture, manifest,
artifact-size/hash and license checks. Add the explicit compact candidate as a
new identity if appropriate; never relabel the old digest or transfer its evidence.
Check pinned Ollama/OpenClaw compatibility and actual supported thinking mode.
Publisher capability claims remain unverified until locally tested.

`catalog.validate` and the updater currently require eight to twelve entries;
tests assume nine. Replace those historical product-count requirements with a
reviewed bounded policy supporting this smaller lineup and explicit legacy
inventory. Keep duplicate-tag, local-only, metadata, licensing, checksum and
resource protections. Test small valid catalogs and malformed/oversized catalogs;
do not weaken artifact validation to obtain fewer entries.

## One upgrade journey

1. From the debrief, show one candidate with a hypothesis tied to a measured miss.
   Offer Keep current and a collapsed comparison of the other eligible choices.
2. Show download bytes still needed, memory estimate at the actual proposed
   context, GPU/CPU uncertainty and likely latency tradeoff. Fit is advisory;
   exclude unknown or insufficient fit from automatic recommendations, with a
   visible reason. Count all MoE weights and runtime/cache overhead.
3. If needed, choose storage inline: named destinations, available/required space,
   encryption and reboot behavior, folder preview, Review then Use this location.
   Explain blocked drives. Run the existing explicit write check. Keep the starter
   usable; never format, auto-adopt DATA, move stores or widen permissions.
4. Download and verify through existing jobs. Show real byte progress, pause/resume
   where supported, cancellation and concrete no-space/offline errors. Downloads
   do not activate models. Existing verified installed candidates skip acquisition.
5. Review the exact current and candidate identities, what changes, and the
   restoration route. Confirm Try this model using the existing transaction owner.
   Show verification, assistant pause, startup and failure/recovery as real phases.
6. Return to the same mission with the source result attached. Use J7's explicit
   model-intervention comparison, holding other settings constant. Preserve fixed
   criteria; explain gains, misses and speed separately. Bigger may lose.
7. Keep or Restore must act on the actual assistant model transaction, unlike the
   Lab-only instruction experiment. Explain that distinction. Audit the existing
   successful-switch journal: if it cannot retain safe post-success restoration,
   extend it narrowly rather than implementing a second configuration writer.
   Preserve owner edits, profile/history, credentials and permissions. Never erase
   either model. Validate interrupted and failed recovery before enabling the action.

## Acceptance

- New owner completes an upgrade from a mission without finding a separate storage
  panel, entering paths or using a terminal. One next action remains dominant at
  320/390px and desktop; keyboard and reduced motion work.
- Candidate ranking has deterministic rationale and no spending/size score.
  Missing hardware, storage refusal, no space, offline, cancellation, digest change,
  unsupported model, failed startup and owner edits preserve safe exits.
- Hidden legacy entries remain usable for current state and restoration. A changed
  manifest cannot inherit qualification. Document migration/version behavior.
- Real larger-model switch, gateway reply, matched retest and post-success restore
  are separate integration gates. Fixture rendering is not their acceptance.
- Record actual screenshots and a reviewer completing the flow. Reuse existing
  transactions and download controls; do not bump pinned runtimes or build an ISO
  until the integrated play session is reviewable and source gates pass.
