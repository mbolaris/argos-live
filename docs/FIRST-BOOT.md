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
OpenClaw first chat, downloaded-model switching and physical persistence/GPU
acceptance remain separate. Fixture mode tests do not prove a physical encrypted
persistence reboot.
