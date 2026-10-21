"""Opt-in LAN relay; the managed dashboard remains on loopback."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import time
import threading
from urllib.parse import parse_qs, quote, urlsplit
from argoslive.desktop import session_url


class Relay(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host, port, session):
        self.session = Path(session)
        self.code = ''.join(secrets.choice('0123456789') for _ in range(8))
        self.attempts = []
        self.pair_lock = threading.Lock()
        super().__init__((host, port), Handler)

    @property
    def origin(self):
        return f'http://{self.server_address[0]}:{self.server_port}'

    def backend(self):
        info = self.session.stat()
        if os.name != 'nt' and info.st_mode & 0o077:
            raise ValueError('Session file must be private')
        return session_url(json.loads(self.session.read_text()))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # URLs carry private bearer credentials.

    def reply(self, status, body=b'', **headers):
        self.send_response(status)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', headers.pop('Referrer_Policy', 'no-referrer'))
        if not any(key.lower() == 'content_type' for key in headers):
            headers['Content_Type'] = 'text/plain; charset=utf-8'
        if not body and status >= 400:
            body = {403: b'Access denied. Open the LAN home page and pair again.',
                    503: b'Argos is restarting. Try again shortly.'}.get(status, b'Request could not be completed.')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        for key, value in headers.items():
            self.send_header(key.replace('_', '-'), value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
        self.close_connection = True

    def request(self):
        expected = urlsplit(self.server.origin).netloc
        origins = self.headers.get_all('Origin') or []
        if self.headers.get_all('Host') != [expected] or (origins and origins != [self.server.origin]):
            return self.reply(403)
        if len(self.headers.get_all('X-Argos-Token') or []) > 1:
            return self.reply(403)
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or self.headers.get('Transfer-Encoding'):
            return self.reply(400)
        try:
            lengths = self.headers.get_all('Content-Length') or ['0']
            if len(lengths) != 1:
                raise ValueError()
            length = int(lengths[0])
            if not 0 <= length <= 65536:
                raise ValueError()
        except ValueError:
            return self.reply(400)
        body = self.rfile.read(length)
        if parsed.path == '/pair' or (parsed.path == '/' and not parsed.query):
            if self.command in ['GET', 'HEAD']:
                page = b'''<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1"><title>Connect to Argos</title><body style="background:#0b1721;color:#e5f5ff;font:18px system-ui;max-width:420px;margin:60px auto;padding:24px"><h1>Connect to your AI</h1><p>Enter the 8-digit code shown on Toronado.</p><form method="post" action="/pair"><input name="code" type="password" inputmode="numeric" pattern="[0-9]{8}" maxlength="8" autocomplete="off" required aria-label="Pairing code" style="font:24px system-ui;width:100%;box-sizing:border-box;padding:14px"><button style="font:18px system-ui;width:100%;padding:14px;margin-top:16px">Open Argos</button></form>'''
                # no-referrer makes browser form POSTs carry Origin: null.
                # Preserve same-origin form authentication without leaking referrers off-site.
                return self.reply(200, page, Content_Type='text/html; charset=utf-8', Referrer_Policy='same-origin', Content_Security_Policy="default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
            now = time.monotonic()
            with self.server.pair_lock:
                self.server.attempts = [t for t in self.server.attempts if now-t < 60]
                if len(self.server.attempts) >= 5:
                    return self.reply(429, b'Too many attempts. Wait one minute.')
                self.server.attempts.append(now)
            try:
                code = parse_qs(body.decode('ascii'), max_num_fields=1).get('code', [''])[0]
                if not secrets.compare_digest(code, self.server.code):
                    return self.reply(403, b'Incorrect code. Go back and try again.')
                _, token = self.server.backend()
                return self.reply(303, Location='/?token='+quote(token))
            except (ValueError, OSError):
                return self.reply(503)
        upstream = None
        try:
            origin, _ = self.server.backend()
            headers = {k:v for k,v in self.headers.items() if k.lower() in ['content-type', 'x-argos-token']}
            headers['Host'] = urlsplit(origin).netloc
            if origins:
                headers['Origin'] = origin
            upstream = http.client.HTTPConnection('127.0.0.1', urlsplit(origin).port, timeout=90)
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            content = response.read()
            forwarded = {k.replace('-', '_'):v for k,v in response.getheaders() if k.lower() in ['content-type','content-security-policy','content-disposition']}
            return self.reply(response.status, content, **forwarded)
        except (OSError, ValueError, http.client.HTTPException):
            return self.reply(503, b'Argos is restarting. Try again shortly.')
        finally:
            if upstream:
                upstream.close()

    do_GET = request
    do_HEAD = request
    do_POST = request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='Exact private IPv4 LAN address')
    parser.add_argument('--port', type=int, default=44429)
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.host)
    if not any(address in ipaddress.IPv4Network(n) for n in ['10.0.0.0/8','172.16.0.0/12','192.168.0.0/16']):
        parser.error('Choose an exact private LAN address')
    state = Path.home()/'.local/state/argos-live'
    with Relay(args.host, args.port, state/'desktop-session.json') as server:
        server.backend()
        pairing = state/'lan-pairing.txt'
        descriptor = os.open(pairing, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as f:
            f.write(f'Open {server.origin} on your phone.\nPairing code: {server.code}\nKeep this code private. LAN access stops when this relay stops.\n')
        try:
            server.serve_forever()
        finally:
            pairing.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
