# Proposed starter model catalog

> Next implementation target: [CURATED-MODEL-JOURNEY.md](CURATED-MODEL-JOURNEY.md).
> The nine-entry table below records existing metadata, not the future recommended
> shortlist. Preserve legacy identities for installed models and restoration.
> Audit the 4B alias/architecture mismatch before refreshing metadata.

This is the MD1 list for owner review under D4. The catalog is public metadata, not an agent assignment or automatic download. It adds no software backend or private personality. `argos catalog [--json]` works offline and lists the accepted metadata; choosing/downloading/testing a model remains a separate step.

| Exact Ollama tag | Download GiB (artifact bytes) | Intended use |
|---|---:|---|
| qwen3:0.6b | 0.49 | Existing small offline starter |
| qwen3:1.7b | 1.27 | Small-memory assistant experiment |
| qwen3:4b | 2.33 | Compact general assistant |
| qwen3:8b | 4.87 | Midrange reasoning and conversation |
| qwen3:14b | 8.64 | Larger general assistant |
| qwen3:30b | 17.28 | Mixture-of-experts experiment |
| qwen3-vl:4b | 3.07 | Vision experiment |
| qwen2.5-coder:7b | 4.36 | Coding experiment |
| huihui_ai/qwen3-abliterated:8b | 4.68 | Optional community discussion-model experiment |

These checked revisions use Q4_K_M and carry Apache-2.0 license blobs, shipped under `argoslive/data/licenses/` and checked when loading the catalog. Download sizes count each distinct manifest artifact once, including config/template/license/parameter files; HTTP overhead and manifest JSON are outside that total. Installed shared blobs can reduce a later job's missing bytes. Tag names and registry parameter labels differ: `parameter_count` reflects the registry's rounded model-type label, not a tensor census.

The small-to-large range makes resource comparisons useful across machines. The community entry is optional, not a silent replacement for Nyx's private preference. No Argos/Nyx/Proteus model is automatically assigned. The abliterated entry's cache estimate uses its published base Qwen3-8B architecture; it does not prove that a private Windows alias or another community revision is equivalent.

Each manifest is pinned by its full raw SHA256. Small config/license blobs are fetched and verified against their declared sizes/digests; weight blobs are never fetched by the updater. Architecture config JSON is fetched from a revision-pinned upstream source and its hash is recorded. Capabilities are publisher claims with `capability_verified: false`, not measured scores or readiness. Pinned Ollama/OpenClaw acceptance must establish actual chat, tool and image functionality after a verified pull.

`qwen3-coder:30b` was considered but excluded: its registry config descriptor declared 539 bytes while the hash-matching blob contained 542 bytes. The updater refuses this inconsistency. The catalog instead proposes the smaller coding entry above; it does not remap any private model preference to it.

`catalog.fit()` estimates full weight bytes plus a full-context f16 K/V cache (layers × KV heads × head dimension × context × two caches × two bytes), plus max(512 MiB, 10% of weight bytes) overhead. Vision adds another 512 MiB estimated reserve. Default context is 32,768, matching current Argos runtime configuration; callers can request a different context explicitly. `fits` needs at least 10% headroom above the estimate; `tight` covers the estimate with less headroom; `won't fit` is below it; missing measured capacity is `unknown`. Compare against free VRAM for full GPU residency or available RAM for CPU use. All MoE weights count, not just active parameters. These are conservative planning assumptions, not guarantees: cache format, vision input, allocator behavior, host-side allocations and split offload affect real use. No automatic fallback follows a fit result.

Pack import now resolves exact catalog names/quantization to `in catalog` with `ready: false`. Only the distinct installed-and-verified inventory accepted by P4 can activate a model. Source-only aliases remain unresolved. The CLI does not upgrade a catalog entry to installed merely because metadata exists.

To refresh, run `python3 scripts/update-catalog.py` in a checkout. It builds the whole candidate before replacing the catalog; missing metadata, changed family/quantization, unreviewed license hashes, checksum/size discrepancies and unavailable immutable architecture revisions fail the refresh. It never changes `versions.env`, running services, owner state or model weights. Review the diff and approve new model/licence choices in the PR before promotion. Allowed public metadata hosts/CDN are explicit; a changed CDN requires a reviewed update. The catalog includes upstream publisher URLs for capability review: [Qwen3](https://ollama.com/library/qwen3), [vision](https://ollama.com/library/qwen3-vl), [coding](https://ollama.com/library/qwen2.5-coder), and the [community publisher](https://ollama.com/huihui_ai/qwen3-abliterated).
