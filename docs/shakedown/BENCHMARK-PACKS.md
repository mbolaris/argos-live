# Benchmark packs

Benchmark packs add small, fixed subsets of public evaluations to Shakedown. Argos ships
manifest metadata and adapters; benchmark questions and answers stay out of the repository.
The owner downloads the pinned source files to the local data directory after reviewing the
upstream licence. Every file is checked against its pinned size and SHA-256 before use. A
modified or incomplete file is refused.

## Review and download

Use `argos bench packs status` to see available packs and their local state. Review one before
downloading it with `argos bench packs review <pack>`. The review shows the source revision,
file hashes, licence identifiers and licence URLs. For a gated source it also shows the upstream
terms URL. Nothing downloads until the owner explicitly repeats the command with
`--accept-licences`; gated sources also require `--accept-terms`. Downloads are owner initiated,
one at a time, and are never uploaded.

The Shakedown page exposes the same review and confirmation flow. It reports transfer progress
and can cancel an active download. A pack's questions and answers are built in memory from the
verified local files only.

## Manifest format

Each `runtime/argoslive/data/shakedown/packs/<pack>.json` file uses
`argos-benchmark-pack/1`. It records a stable pack identifier and version, a pinned upstream
revision, one or more source files with exact sizes and SHA-256 hashes, licence records for the
dataset and (when distinct) the selection, whether upstream terms gate access, a versioned list
of item IDs, and nested quick, standard and full slices. Source URLs must use HTTPS and a reviewed
host. The manifest contains no question or answer text.

An adapter named by the manifest parses those source files into the existing
`argos-ability-suite/1` shape. The pack loader checks that the adapter produces the exact pinned
item list and that every answer reference, deliberate wrong answer and malformed example agrees
with the existing scorer. Pack runs are identified in saved results as public subsets and never
as official benchmark scores.

The owner’s acceptance receipt and downloaded files live under
`~/.local/share/argos-live/benchmark-packs/`, outside the image. The receipt binds acceptance to
the exact revision and licence record. Offline status checks use only local manifests and files.

No pack ships until its upstream dataset and selection licences have been reviewed and recorded.
The absence of a pack from the list means there is no reviewed manifest for it in this build.
