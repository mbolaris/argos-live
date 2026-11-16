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
host. The upstream revision identifies the reviewed source revision; each file's exact bytes are
pinned by its size and SHA-256, including when an upstream project serves an archive at a stable
URL. The manifest contains no question or answer text.

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

## Initial packs

The first two packs use MIT-licensed source material. MMLU selects 100 test questions across its
57 subjects: `floor(row_count / 2)` for each subject, then `floor(row_count / 3)` for the first
43 subjects ordered by SHA-256 of `argos-mmlu-100-v1/<subject>`. Its quick and standard slices
take the first 25 and 50 items from that fixed list. The source archive is the official MMLU test
download linked by the [upstream repository](https://github.com/hendrycks/test); the adapter reads only `data/test`
entries from the tar archive. The archive is 166 MB and is fetched only after owner confirmation.

GSM8K selects rows `floor(i * 1318 / 99)` for `i = 0..99` from the official 1,319-row test split
in the [upstream repository](https://github.com/openai/grade-school-math). Its quick and standard slices
take the first 25 and 50 items. The scorer accepts one readable final number; an answer in any
other format is a miss. The adapter removes GSM8K's worked solution and retains only the final
number as its scoring reference in memory. Format misses are shown as “No readable answer.”

The tinyBenchmarks selections are not used for these packs because their dataset cards do not
declare a licence for the selected artifacts. The MMLU and GSM8K source licences and the fixed
selection records are recorded in their manifests.
