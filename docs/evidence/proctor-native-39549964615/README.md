# Real bundled-model practice completion

[Hosted run 39549964615](https://github.com/mbolaris/argos-live/actions/runs/39549964615)
passed from source `b082674`, whose production runtime matches `ef474e0`.
It used the pinned real OpenClaw/Ollama runtimes and verified `qwen3:0.6b`
artifacts, not a scripted model or synthetic answers.

Saved transcript `84e82ab6b9c1189476fca2ecba37b98e` reached COMPLETED with four
recorded answers, both modules SUBMITTED, zero unanswered items, and three
correct answers. It required three host-managed SDK turns. The signed subject
records `host_bounded_turns/2` and automatic submission only after every item
has an agent-supplied answer. The wire observer saw all seven Proctor tools on
the final request. The service did not trust the model's premature prose claim
that the exam was complete; completion comes from the signed host state.

`transcript.json` contains the public pilot transcript and fixture public key;
no private signing key or owner workspace is included. `local-verification.json`
records a separate local Ed25519/hash check against that same artifact key.
This confirms internal integrity, not independent trust in a production signer.
Payload SHA-256: `8cf618eb673bc096308b8af8027b3a27ada7c401b079c73159f5aee9499799a4`.

This uncalibrated public pilot tests service workflow. It is not proof of an
ability gain, a complete self-improvement campaign, image acceptance, protected
service identity, independent replication or physical Toronado acceptance.
Prior failed attempts remain failures in the coordination record and CI.
