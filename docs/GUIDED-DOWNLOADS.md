# Guided model acquisition

The managed desktop catalog now offers a review dialog showing the exact tag,
download size, license and advisory GPU fit. Only **Pause chat, download and
verify** starts an operation. Dismissing the review makes no changes.
**Applications → Argos Model Lab** reopens the managed dashboard using the existing
verified desktop session, so the lab remains discoverable after chat opens.

Acquisition and benchmarks share the desktop workload reservation. The owned
assistant is paused and its resources released first. A download uses the existing
`OnboardingQueue` pipeline, private durable receipts and the configured identity-
marked model store. The pipeline checks the current registry revision, full
artifact hashes, model metadata and a short local reply before publishing files.
An unrelated service is never adopted. This action does not activate the model,
change permissions, download credentials or edit the assistant configuration.

The page shows bytes, recently measured MiB/s and ETA when available. Pause/cancel
requests are durable. Explicit retry reuses the same job/staged files and rechecks
catalog/storage identity; cancelled jobs stay cancelled. Partials are retained,
never silently erased. A cancellation before acquisition begins also settles the
receipt instead of leaving a cancelled job queued. One-hour acquisition budget
requests cancellation, with in-flight requests/verification and cleanup bounded
by their existing operations; this is not a one-hour exact termination promise.
Shutdown signals cancellation even when writing a durable control fails.

After resource cleanup, the prior assistant startup is requested. An initially
stopped assistant stays stopped. The onboarding reply sample may display actual
output counts/rate; it is distinct from repeated benchmark results and says
nothing about vision/tool acceptance. Switching the active model and recording
its new baseline are the next step. Deletion and broader addon setup remain
separate work.

The public CI acquisition smoke exercises this desktop adapter's explicit resume
using its existing real partial pull, rather than downloading another model.
Full managed restart is independently tested by the native desktop/lab smoke.
Browser fixture tests check review, dismissal, acquisition, visible throughput,
workload exclusion and pause. Native/ISO/physical acceptance must be reported
separately; this source change does not update an existing USB.
