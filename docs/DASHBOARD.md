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

`GET /api/status` reports dashboard liveness and an unverified assistant state.
`GET /api/capabilities` exposes the conservative pinned addon inventory. The
offline page renders capability candidates and their pending requirements. It
does not claim assistant readiness, infer owner permissions, load plugins, start
models, read private agent configuration, or install dependencies. Existing
conversation and first-boot behavior stays with the welcome window until W2/O2
and W6 add and verify the replacement flow.

W1 acceptance uses disposable loopback HTTP fixtures: tokens, origin/host
checks, static/JSON responses, traversal rejection, method policy, generic
errors, no token access logs, per-session uniqueness, and clean server shutdown.
Linux CI also verifies installed-package assets. A browser rendering check and
Firefox ESR/physical ISO acceptance are W2 and C3 work, not claimed by W1.
