"""Loopback dashboard foundation. No model/configuration mutation endpoints."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, quote, urlsplit

from argoslive import addons

ASSETS = Path(__file__).with_name('static')
FILES = {'/': ('index.html', 'text/html; charset=utf-8'),
         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
         '/style.css': ('style.css', 'text/css; charset=utf-8')}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, host='127.0.0.1', port=8765):
        # Explicit IPv4 loopback prevents wildcard, DNS and LAN binding surprises.
        if host != '127.0.0.1':
            raise ValueError('Dashboard bind must be 127.0.0.1')
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Invalid dashboard port')
        self.token = secrets.token_urlsafe(32)
        super().__init__((host, port), Handler)

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.server_port}'

    @property
    def url(self):
        return self.origin + '/?token=' + quote(self.token)


class Handler(BaseHTTPRequestHandler):
    server_version = 'ArgosDashboard'

    def log_message(self, *args):
        # Default access logging would expose the session token in request URLs.
        pass

    def reply(self, status, body, content_type='application/json; charset=utf-8', *, head=False):
        if isinstance(body, dict):
            body = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        if not head and self.command != 'HEAD':
            self.wfile.write(body)

    def authorized(self, *, mutation=False):
        expected_host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get_all('Host') != [expected_host]:
            self.reply(403, {'error': 'Invalid dashboard host'})
            return False
        origins = self.headers.get_all('Origin') or []
        if origins and origins != [self.server.origin]:
            self.reply(403, {'error': 'Cross-origin request rejected'})
            return False
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc:
                raise ValueError('Absolute request target')
            query = parse_qs(parsed.query, max_num_fields=20)
        except ValueError:
            self.reply(400, {'error': 'Invalid request target'})
            return False
        tokens = self.headers.get_all('X-Argos-Token')
        # POSTs must carry a header token. A query alone cannot authorize mutation.
        if not tokens and not mutation:
            tokens = query.get('token')
        token = tokens[0] if tokens and len(tokens) == 1 else ''
        if not secrets.compare_digest(token.encode('utf-8'), self.server.token.encode('ascii')):
            self.reply(403, {'error': 'Session token required'})
            return False
        return True

    def do_GET(self, *, head=False):
        if not self.authorized():
            return
        path = urlsplit(self.path).path
        if path == '/api/status':
            self.reply(200, {'schema': 'argos-dashboard/1', 'dashboard': 'running',
                             'assistant': 'not-checked', 'mode': 'read-only-preview'}, head=head)
        elif path == '/api/capabilities':
            try:
                result = addons.inventory(addons.load())
            except (OSError, ValueError, TypeError, KeyError):
                self.reply(503, {'error': 'Capability inventory unavailable'}, head=head)
            else:
                self.reply(200, result, head=head)
        elif path in FILES:
            filename, mime = FILES[path]
            try:
                body = (ASSETS / filename).read_bytes()
                if path == '/':
                    body = body.replace(b'__SESSION_TOKEN__', quote(self.server.token).encode('ascii'))
            except OSError:
                self.reply(503, {'error': 'Dashboard asset unavailable'}, head=head)
            else:
                self.reply(200, body, mime, head=head)
        else:
            self.reply(404, {'error': 'Unknown dashboard route'}, head=head)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_POST(self):
        if self.authorized(mutation=True):
            self.reply(405, {'error': 'Dashboard preview has no mutation routes'})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    with DashboardServer(args.host, args.port) as server:
        # A URL is printed only to the launching desktop user's terminal, never
        # to HTTP access logs or a persistent file. Automatic launch is W2/O2.
        print('Open this local dashboard URL: ' + server.url, flush=True)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
