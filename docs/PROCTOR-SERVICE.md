# Owner-started Proctor service

`argos proctor practice` starts a host-selected practice session through a fresh,
private OpenClaw gateway profile. The profile preserves the selected local
Ollama model and its reasoning controls, grants only the `argos_proctor_*`
tools, disables bundled skills and heartbeat activity, and enables the plugin's
host admission hooks. The host owns the cartridge, caller and token keys,
signing key, subject snapshot, workload reservation, and transcript finalization.
The signed transcript is saved before the Proctor reservation is released.
Before practice, the host verifies the selected catalog manifest and every
declared model blob. The signed subject snapshot includes a digest of the
catalog manifest, the local manifest bytes, and each verified artifact digest,
size, and media type; it does not copy model weights into the transcript.

The command uses the bundled `pilot-a` cartridge unless the owner supplies a
compiled cartridge and form. The bundled four-item pilot exists to exercise the
tool flow and feedback path. Pilot v1.1 allows three minutes per module because
native SDK round trips in the recorded CPU test took roughly twenty to thirty
seconds each; the previous one-minute pilot expired before submission. This
changes only the public uncalibrated pilot, not assessment timings. It cannot verify
general ability or establish an improvement. After a terminal practice session,
the host receives aggregate scores and item-level submitted/expected answers to
support coaching. If bounded host continuation ends before submission, the host closes the
session as `ABANDONED`, signs the partial transcript, and reports an incomplete
practice. A clean worker that never starts the exam produces a signed zero-item
ABANDONED receipt without releasing any questions after the bounded start attempts; this is incomplete evidence
and cannot pass image acceptance or start improvement. The launch prompt names
argos_proctor_start({}) as the required first action. Assessment and held-out
exams remain outside this entry point.

The host can continue a practice exam across short agent turns. It verifies
each SDK worker and process group has exited before admitting another turn,
retains the same exclusive workload reservation and exam, and fences off the
previous turn's credentials. For an unanswered item, the host surfaces exactly
that active question in the next bounded turn and records which item was shown.
The answer tool accepts the agent's item identifier and answer; the host binds
it only to an item surfaced in the same active module. The model can also fetch
questions through the item tool. It submits a module after
every item has a recorded agent answer and the worker has drained. It never
fills in an answer. This automatic submission policy is
recorded in the signed administration conditions. Breaks and deadlines remain host-owned.
The signed subject configuration records this administration mode. Sixteen
turns, thirty minutes, or two consecutive turns without progress bound this
coaching procedure; an unfinished exam is signed as ABANDONED. Uncertain
workers still quarantine the workload. Assessment and held-out sessions do not
use this continuation policy.

Start, status, answer, submit and continue responses include a `next_step`
tool name and arguments to help the agent navigate the exam. After fetching an
item, the agent must solve it and supply its own answer. Navigation uses only
the exam state and recorded answer revisions; an incorrect recorded answer
advances the same way as a correct one. It never exposes correctness or chooses
an answer. Practice feedback is suggested only after completion; held-out exams
never offer it. These hints do not force an agent to continue, and the real-model
image test must still prove completion.

The plugin renders the next action in plain text as well as JSON. A question
response explicitly asks the agent to solve it and call the answer tool with
the surfaced item identifier and its own answer; the controller accepts only
items surfaced by the host or retrieved through the item tool. Recording an
answer explicitly asks it to continue or submit. These
directions carry no answer hints and do not turn an incomplete attempt into a
pass.

Fresh image configurations request temperature zero explicitly. Two separate
native fixture runs (39550951768 and 39550954625) completed all four pilot items
at that setting, with the actual request temperature observed on the wire.
Each scored 3/4; this is limited workflow repeatability evidence, not an ability
gain. Existing owner configurations remain byte-for-byte unchanged, and the
private Proctor profile still preserves their selected generation controls.

`argos proctor improve` runs that practice session first, waits for its signed
transcript to be saved and its reservation to drain, then starts a separate
host-admitted improvement campaign. The campaign receives practice misses as
coaching context and gets only the managed Argos evaluation, comparison,
logging, and reversible instruction-change tools. Host admission owns one
workload reservation at a time, and the controller saves evaluations even if
the campaign agent turn ends. Practice scores never count as evidence that an
ability improved. The campaign follows the installed Argos improvement skill
for matched baseline/candidate runs, keep/restore decisions, and saved run IDs.
An incomplete practice is retained for review and never starts a campaign.
An exam whose timer reached a terminal state with unanswered items also remains
incomplete for this purpose; timed completion cannot unlock a campaign.

The service refuses to start if the everyday OpenClaw gateway or Ollama already
occupies its loopback port. Close the everyday assistant first; the Proctor
command then owns and shuts down both its private Ollama process and gateway.

Example:

```sh
argos proctor practice
argos proctor practice --cartridge /path/to/reviewed-cartridge.sqlite3 --form practice-a --json
argos proctor improve
```

This is declared/cooperative enforcement within the same Argos user account.
It does not protect keys or files against another process with the same UID,
prove which weights the inference backend actually loaded after startup,
prevent direct access to the local Ollama API, or reserve the GPU against an
unrelated gateway that bypasses Argos workload admission.
The exact-image hosted service smoke requires the owner entry point, scoped
tools, managed gateway lifecycle, a signed completed practice
receipt with all four items answered, bound to the bundled model identity, and assistant recovery. Incomplete
receipts remain saved diagnostic evidence and fail the acceptance gate. Synthetic
integration tests separately verify scoped tool and reservation behavior. The
smoke does not attest which weights Ollama loaded at inference time. A Toronado
exam still requires a reviewed exclusive slot, verified model/config snapshot,
calibrated forms for ability claims, and independent transcript auditing.

The native-chat CI workflow also exercises the real service with the same
verified bundled model, before requiring an ISO rebuild. It uses disposable
storage discovery and the real gateway, exam, model-generated answers and
signer. It requires four recorded answers and signed completion, preserving the
receipt, transcript and public verification key. It is a public-pilot regression
test; it does not establish image acceptance or general ability.
