# First-boot setup

`argos setup --auto` configures a fresh Live session without questions. It verifies
the bundled starter's manifest, artifact hashes and read-only source, then uses
the storage planner to choose a dedicated location for future managed downloads.
Only a marker is written to that model directory; starter weights stay in the
image. Each later pull checks the selected volume identity and actual model space
budget separately. The command does not mount/unlock a disk, download a model,
start a daemon or open a browser.

The generated OpenClaw configuration keeps loopback/token authentication,
conversation-only tools, denied shell/files/browser/web/update controls and no
elevated tools. Account credentials are not requested. Configuration and workspace
stay under the desktop user's home, outside the model store; files are private.
Settings mode (`try` or `persistent`), observed persistence encryption and model
store encryption are distinct. Unknown encryption remains unknown. Public model
weights on DATA do not imply private personality data belongs there.

Existing Argos state and OpenClaw configuration are reused unchanged after storage
identity checks. A mismatched/missing volume, existing OpenClaw files without Argos
state, a nonempty proposed model store, linked paths or an unavailable persistence
probe stops setup for review. No alternate location is silently adopted. Complete
configuration files publish without overwriting a racing owner file. On ordinary
failure, only unchanged files created by the transaction and empty newly created
directories are removed; owner changes remain intact. Interrupted/incomplete state
is retained for review rather than replaced.

`argos setup --auto --json` reports setup metadata without its generated gateway
token. Interactive `argos setup` keeps its existing prompts and seed-copy behavior.
For automatically configured sessions, `argos start` points inference at the
verified image seed; managed downloads continue through `argos pull`. Explicit
model selection switches to the selected writable model store, or back to the
image when the starter is chosen. `argos verify` checks the seed and any managed
model artifacts. These source switches require restarting the assistant; model
assignment does not itself download weights or establish tool capability.

The no-NIC [VM acceptance run](https://github.com/mbolaris/argos-live/actions/runs/37233824509)
passed questionless setup, immutable SquashFS starter CPU inference without weight
copies, saved benchmarks and the native Firefox dashboard. The test explicitly
starts services; automatic desktop startup and progress remain O2. Native
OpenClaw embedded first chat separately passed the pinned hosted test; downloaded-model switching and physical persistence/GPU
acceptance remain separate. Fixture mode tests do not prove a physical encrypted
persistence reboot.

## Managed desktop candidate

`argos desktop` opens the local dashboard immediately and prepares the assistant
in the background without setup questions. It verifies the selected model, starts
owned Ollama, measures a bounded warmup reply, then starts the local token gateway.
The page shows actual stages, first-token timing and backend-reported generation
rate; unavailable measurements remain unknown. It opens the conversation once
ready. Reopening the workspace reuses its verified session rather than starting
another service. Start/Stop actions control only this launcher's owned job.

The launcher accepts the reviewed local conversation profile. An existing broader
or changed policy, channel configuration, unresolved model or unavailable storage
stops automatic startup for review; nothing is reset or silently reconfigured.
Stop during model/gateway startup cancels the job and releases owned services.
Filesystem hashing and initial health probes can take time before cancellation
returns; the page stays at Stopping until cleanup finishes. Cold model service
startup has a bounded 180-second grace period and warmup has a 600-second socket
read budget. Stop during blocked warmup releases the owned backend; it does not
wait for a full prefill/read timeout. A pending reply reader prevents a new start
until it finishes. These budgets are not promises of first-boot speed.

Logs and the private session descriptor live under `~/.local/state/argos-live/`.
The managed backend writes stdout/stderr to `.argos-daemon-lease/ollama.log`
under that directory; gateway and startup logs remain alongside it. Native logs
must be owner-only regular files; linked or broadly readable files refuse startup.
Do not publish raw backend logs or copy them into the public model store.
Descriptors are removed only if still matching this launch. Private diagnostics
do not appear in public HTTP responses or access logs. In try mode, workspace and
conversation changes can be lost at reboot; persistence and model-store encryption
remain separate status cards. No private configuration is moved to DATA.

The desktop login hook uses this candidate launcher; legacy welcome code remains
packaged during acceptance. Hosted domain and browser tests are separate from
fresh ISO/Firefox/firmware and physical persistence/GPU acceptance. Do not promote
or rewrite a USB solely from hosted startup evidence.

The [native managed acceptance run](https://github.com/mbolaris/argos-live/actions/runs/37238664640)
passed actual pinned setup, local CPU warmup, gateway startup, verified session
reopen, repeated-start reuse, one-time chat URL handoff and clean shutdown. It
confirmed unchanged configuration and no copied model weights. It did not open
the browser conversation. Warmup numbers describe a short measured reply on the
hosted test machine; use the longer benchmark suites for model comparisons.
