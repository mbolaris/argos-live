# Private LAN dashboard access

The optional relay lets a phone on the same trusted home network use the dashboard while the managed server stays bound to loopback. It does not expose OpenClaw's separate chat server.

Run as the desktop owner, with an active managed desktop session:

```sh
PYTHONPATH=/usr/local/lib/argos-live python3 -m argoslive.lan --host 192.168.1.46 --port 44429
```

Choose the machine's exact private IPv4 address. The relay binds only that address. Open `http://192.168.1.46:44429` on the phone, then enter the eight-digit code from the owner's private `~/.local/state/argos-live/lan-pairing.txt`. Display that file locally; do not publish it. Pairing grants the dashboard's existing authority, including its settings and test controls. HTTP is intended for a trusted LAN; no router port forwarding is needed or intended.

Five pairing attempts are allowed per minute across clients. Successful pairing redirects to the current private dashboard session link. The backend still enforces its token on every request; POST requests still require the token header. The relay validates LAN Host/Origin before translating them to the fixed loopback destination. Tokens and codes are omitted from access logs. If the desktop restarts, pair again for its new token.

Stop the relay with Ctrl+C. This command does not install an autostart service, change firewall rules, or modify the backend session. The pairing file is removed on a normal exit. Desktop-only chat links and local file pickers do not become phone services.

## Verification

`PYTHONPATH=runtime python3 -m unittest discover -s tests -p test_lan.py -v`

Tests use a real dashboard HTTP server and relay: pairing, rate limiting, backend authentication, Host/Origin rejection, and desktop token rotation.

The pairing form uses `Referrer-Policy: same-origin`: `no-referrer` caused real browser form submissions to carry `Origin: null`, which correctly failed the relay's origin check. Other responses retain `no-referrer`. Error responses have explicit text content types and readable bodies, avoiding empty file downloads on mobile browsers. Regression coverage checks the policy, null-origin rejection, readable errors, and valid same-origin pairing.

Live verification on Toronado: the pairing page was reachable from Yugo over the LAN (HTTP 200), an unauthenticated API request was rejected (403), and a private live check passed pairing plus authenticated dashboard/JavaScript fetches. No benchmark or settings mutation was needed. A physical phone has not yet been tested. The live relay is a separate owner-owned helper using the installed runtime and is enabled only for the current session.

After the owner reported an empty `/pair` download on their iPhone, a Chromium form submission reproduced `Origin: null` and HTTP 403. The corrected live relay was then checked in a mobile viewport from Yugo: actual form submission sent the expected LAN origin, navigated to the authenticated dashboard, and fetched authenticated status successfully with no download. The owner still needs to confirm the corrected flow on the physical iPhone. Restarting only the relay rotated its pairing code; Argos and running trials were not restarted.
