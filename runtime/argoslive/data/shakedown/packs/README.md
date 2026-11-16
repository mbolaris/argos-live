# Benchmark pack manifests

One `<pack>.json` file per public benchmark subset, in the `argos-benchmark-pack/1` format
described in [docs/shakedown/BENCHMARK-PACKS.md](../../../../../docs/shakedown/BENCHMARK-PACKS.md).

This directory holds manifests only: where the upstream files are, their pinned revision and
SHA-256 values, the licence record, and the list of item IDs. It never holds a benchmark question
or answer. The owner downloads the files from their original source; they are stored with the
owner's data and verified by hash before every use.
