# Local dashboard foundation

Run `argos dashboard` (or `python3 web/server.py` from the checkout). The server
listens on `127.0.0.1:8765` and prints a fresh session URL to the launching user's
terminal. Open that URL locally. `--port` selects another port; other bind
addresses are refused. Ctrl+C closes the listener. There is no automatic browser
launch, desktop autostart or replacement of the existing welcome window yet.

All routes require the session token: GET/HEAD accept `X-Argos-Token` or the
session URL query; POST and other mutation methods require the header and still
return 405 because this preview has no mutation routes. Host and Origin must
match the bound loopback endpoint. Responses disable caching, referrer forwarding
and embedding. Access logs are suppressed so URL tokens are not persisted.
The server serves only an explicit asset map, never arbitrary filesystem paths.

`GET /api/status` reports read-only CPU/RAM/GPU measurements, free model-storage
space after identity validation, observed encryption, live persistence/temporary
mode, default-route presence, Ollama health/version and reported loaded-model
CPU/GPU/split placement. Unknown values stay null. The endpoint does not verify
Ollama ownership, internet access or successful model inference. It does not run
the legacy storage write probe or create files. Ambiguous encryption is unknown.

`GET /api/assistant/chat` rechecks the configured local-only gateway's readiness
and returns its token-based chat URL to the authenticated dashboard client. The
gateway credential appears only in the URL fragment, not in HTTP request paths
or the status response. Unsupported authentication or unavailable gateways leave
chat disabled. The dashboard reuses the running gateway and never starts a
second instance; startup/setup remains in the existing welcome window.
`GET /api/capabilities` exposes the conservative pinned addon inventory. The
offline page renders capability candidates and their pending requirements. It
does not prove a successful assistant/model reply, infer owner permissions, load
plugins, start models, or install dependencies. Status reads the desktop user's
storage selection and gateway settings, excluding raw configuration and secrets
from the status output. Existing
conversation and first-boot behavior stays with the welcome window until W2/O2
and W6 add and verify the replacement flow.

W1 acceptance uses disposable loopback HTTP fixtures: tokens, origin/host
checks, static/JSON responses, traversal rejection, method policy, generic
errors, no token access logs, per-session uniqueness, and clean server shutdown.
Linux CI also verifies installed-package assets. W2 adds a real headless Chromium
smoke using playwright-core 1.63.0 from the existing checked-in runtime lock,
checking status/capability cards, disabled unconfigured chat, refresh, console
errors and narrow layout. It uses disposable HOME and emits screenshots of CI
hardware only. Chromium is a proxy; Firefox ESR/physical ISO acceptance remains
W2/C3 follow-up.
