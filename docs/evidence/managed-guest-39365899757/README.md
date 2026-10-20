# Managed guest acceptance after controller teardown repair

VM workflow: https://github.com/mbolaris/argos-live/actions/runs/39365899757
Pinned ISO: https://github.com/mbolaris/argos-live/actions/runs/39362908185
Image runtime: 1f64a05; accepted harness/test source: a22c72b.
ISO SHA-256: ec9efe9ae1b994bccd1a800f62566ea829047531cd966413d8b98f9c053a10c5

The offline RAM-only KVM guest completed shipped Firefox baseline activation,
speed/ability saved-run listing and kind checks, and assistant resume with Model
Lab still visible. The saved IDs are fc1904b6c89680af3cf5b037a96175fb and
b818765b6b7b77200b6c98b4ce8d398c. The cropped progress screenshot was reviewed; it
shows the live trial in ability phase, not terminal scoring evidence. result.json
records the subsequent completed lifecycle checks. No model-quality gain or
independent proctor pass is claimed.

Linux Tests 39365904407 passed 803 Python tests (3 skips), syntax and guarded
signal checks. Pinned compatibility 39365904569 passed SDK/controller bridge,
browser, schema/recovery, gateway lifecycle and synthetic generation checks.

The new Linux socket/subprocess regression separately disconnects an evaluation
client, aborts the outer host context, checks continued exclusion while work is
pending, and verifies saved complete coverage and retained controller quarantine.
The VM baseline is normal lifecycle acceptance, not a substitute for that test
or for actual SDK-abort/resource-mediation acceptance.

Failed VM run 39365010610 rendered the dashboard shell before the managed Lab
control loaded. Its guarded target detector refused input. The harness now waits
up to 20 seconds for that specific control and never sends input on expiry. It
does not retry a benchmark. The image bytes did not change for this harness fix.
The first teardown regression run also failed on a test-only misuse of the
Store.list() dictionary; that assertion was corrected before the passing checks.

Direct runArgos abort survival, hard host death and an exposed bounded start/wait
service remain open. No physical firmware/card/persistence/reboot-reset or browser
chat-reply acceptance is claimed. Toronado and generation 36 were not modified.
