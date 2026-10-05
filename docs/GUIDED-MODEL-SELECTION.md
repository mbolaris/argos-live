# Try a verified model

Open **Applications → Argos Model Lab** after chat starts. Save a quick baseline,
review a catalog download, then choose **Review switch** on a downloaded model.
The review shows your current and proposed model and estimated CPU/GPU fit.
Dismissal does nothing. Confirmation pauses chat, verifies the full catalog
manifest and artifact hashes, preserves the current configuration privately,
and starts local inference and the OpenClaw gateway with the selected model.

Only the primary model, its local provider model descriptor, and Argos model
source change. Workspace, personality files, skills, gateway credentials and
permissions stay intact. This control supports the reviewed single-agent
conversation profile. Imported multi-agent profiles need separate review.
The bundled starter remains a selectable fallback without copying its weights.

Failure or cancellation restores the original configuration bytes after owned
services stop. A pending private journal is rolled back at the next desktop
launch after an interrupted write. Concurrent owner edits block rollback and
restart; the private recovery record remains for review. Recovery is never a
reason to overwrite owner edits. No model files are erased.

Successful startup remains in the lab. Choose Open chat, or run the same speed
and quick ability suites to compare generation tokens/sec, first-token latency,
prompt processing rate and tested category scores. Startup warmup is a sample,
not a repeated performance benchmark. Larger models do not guarantee better
answers. Hardware recommendations use measured available RAM and the largest
individual GPU's available VRAM, at the managed 32K context size. Estimates do
not establish actual GPU offload, speed, quality or thermal suitability.

## Acceptance before the next USB update

- Local transaction tests: success, failed startup, cancellation, interrupted
  file pair recovery, workload exclusion and preservation of owner edits.
- Browser proxy: review/dismiss/confirm/cancel, current model, responsive layout,
  benchmark comparisons and explicit download acquisition controls.
- Native pinned Linux: starter reselection through the real owned Ollama and
  OpenClaw services, then an actual OpenClaw local reply. This is not acceptance
  of a larger downloaded model or of browser-submitted chat.
- Fresh image: full checksum/source/manifest verification, offline managed boot
  and visual Firefox review. Physical reboot, encrypted persistence recovery,
  DATA storage, GPU/temperature and a larger-model upgrade remain physical tests.

Do not update the USB until the candidate image gates pass and a fresh
persistence-preserving backup and device geometry are verified.
