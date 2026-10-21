# Temperature-zero practice repetitions

Two independent disposable hosted runs passed on source `3b69a0c`, using the
same pinned real OpenClaw/Ollama stack and verified `qwen3:0.6b` seed. Only the
fixture's requested generation temperature changed; no owner configuration or
model weights changed. The wire observer confirmed temperature zero.

| Run | Saved transcript | Host turns | Recorded answers | Correct |
| --- | --- | --- | --- | --- |
| [39550951768](https://github.com/mbolaris/argos-live/actions/runs/39550951768) | `a2c760e2e71a9c490673c065867e57da` | 3 | 4 | 3 |
| [39550954625](https://github.com/mbolaris/argos-live/actions/runs/39550954625) | `b8ab6ae57358fa766d68c9159faa4adc` | 5 | 4 | 3 |

Both signed records reached COMPLETED with both modules SUBMITTED and zero
unanswered items. Corresponding `proctor-deterministic-<run>` folders preserve
receipts, signed public-pilot transcripts, fixture public keys and separate
local signature/hash checks. The key comes from the same CI artifact, so this
does not establish independent trust in a production signer.

This is limited repeatability evidence for the coaching workflow. It is not an
ability gain or proof of general reliability. The public pilot is uncalibrated;
all earlier failed attempts remain failures. Source `d0ef964` adopts explicit
temperature zero for freshly created image configurations; existing owner
configurations are reused byte-for-byte. A final exact-image VM test and
physical Toronado acceptance remain separate requirements.
