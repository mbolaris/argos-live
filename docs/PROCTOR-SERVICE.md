# Owner-started Proctor practice service

`argos proctor practice` starts a host-selected practice session through a fresh,
private OpenClaw gateway profile. The profile preserves the selected local
Ollama model and its reasoning controls, grants only the `argos_proctor_*`
tools, disables bundled skills and heartbeat activity, and enables the plugin's
host admission hooks. The host owns the cartridge, caller and token keys,
signing key, subject snapshot, workload reservation, and transcript finalization.
The signed transcript is saved before the Proctor reservation is released.

The command uses the bundled `pilot-a` cartridge unless the owner supplies a
compiled cartridge and form. The bundled four-item pilot exists to exercise the
tool flow and feedback path. It is explicitly uncalibrated and cannot verify
general ability or establish an improvement. After a terminal practice session,
the agent gets aggregate scores and item-level submitted/expected answers to
support coaching. Assessment and held-out exams remain outside this entry point.

The service refuses to start if the everyday OpenClaw gateway or Ollama already
occupies its loopback port. Close the everyday assistant first; the Proctor
command then owns and shuts down both its private Ollama process and gateway.

Example:

```sh
argos proctor practice
argos proctor practice --cartridge /path/to/reviewed-cartridge.sqlite3 --form practice-a --json
```

This is declared/cooperative enforcement within the same Argos user account.
It does not protect keys or files against another process with the same UID,
prove model identity, prevent direct access to the local Ollama API, or reserve
the GPU against an unrelated gateway that bypasses Argos workload admission.
The exact-image hosted service smoke verifies the owner entry point, scoped
tools, managed gateway lifecycle, signed receipt, and reservation binding using
a synthetic local model. A Toronado exam still requires a reviewed exclusive
slot, verified model/config snapshot, calibrated forms for ability claims, and
independent transcript auditing.
