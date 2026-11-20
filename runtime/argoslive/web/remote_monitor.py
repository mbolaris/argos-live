"""Private, read-only monitor endpoint for Tailscale Serve."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from argoslive.web import telemetry

ASSETS = Path(__file__).with_name('static')
PORT = 8766


def tailscale_login():
    """Return the local Tailnet account identity, or None when unavailable."""
    executable = shutil.which('tailscale')
    if not executable:
        return None
    try:
        result = subprocess.run([executable, 'status', '--json'], capture_output=True,
                                text=True, timeout=4, check=True)
        value = json.loads(result.stdout)
        if value.get('BackendState') != 'Running':
            return None
        profile = (value.get('Self') or {}).get('UserProfile') or {}
        login = profile.get('LoginName')
        return login if isinstance(login, str) and login and len(login) <= 254 else None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return None


class RemoteMonitorServer(ThreadingHTTPServer):
    """Only monitor assets and read-only projections; never the operator UI."""
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, *, proctor_campaign, store, host='127.0.0.1', port=PORT,
                 allowed_login=None):
        if host != '127.0.0.1' or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Remote monitor must bind to loopback')
        self.proctor_campaign = proctor_campaign
        self.store = store
        # Fail closed until Tailscale is installed, authenticated, and the account
        # identity can be established. The listener remains loopback-only.
        self.allowed_login = allowed_login if allowed_login is not None else tailscale_login()
        super().__init__((host, port), RemoteMonitorHandler)


class RemoteMonitorHandler(BaseHTTPRequestHandler):
    server_version = 'ArgosReadOnlyMonitor'
    routes = {
        '/': ('monitor.html', 'text/html; charset=utf-8'),
        '/monitor.js': ('monitor.js', 'text/javascript; charset=utf-8'),
        '/monitor.css': ('monitor.css', 'text/css; charset=utf-8'),
        '/favicon.svg': ('favicon.svg', 'image/svg+xml'),
    }

    def log_message(self, *_args):
        # Do not retain health or campaign request details.
        pass

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, dict):
            body = json.dumps(body, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        if self.command != 'HEAD':
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def authorized(self):
        allowed = self.server.allowed_login
        supplied = self.headers.get_all('Tailscale-User-Login') or []
        if (not allowed or len(supplied) != 1 or supplied[0] != allowed or
                self.client_address[0] not in ('127.0.0.1', '::1') or
                self.headers.get('X-Forwarded-Proto') != 'https'):
            self.reply(403, {'error': 'Private monitor access required'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            self.reply(400, {'error': 'Invalid request target'})
            return
        path = parsed.path
        if path in self.routes:
            filename, mime = self.routes[path]
            try:
                body = (ASSETS / filename).read_bytes()
            except OSError:
                self.reply(503, {'error': 'Monitor page unavailable'})
                return
            if path == '/':
                body = body.replace(b'__SESSION_TOKEN__', b'')
            self.reply(200, body, mime)
            return
        if parsed.query:
            self.reply(400, {'error': 'Unexpected monitor query'})
            return
        if path == '/api/telemetry':
            self.reply(200, telemetry.snapshot())
            return
        if path == '/api/monitor/campaign':
            try:
                state = (self.server.proctor_campaign.snapshot()
                         if self.server.proctor_campaign else {})
                progress = state.get('progress') if isinstance(state.get('progress'), dict) else {}
                current = progress.get('current') if isinstance(progress.get('current'), dict) else {}
                result = state.get('result') if isinstance(state.get('result'), dict) else {}
                campaign = result.get('campaign') if isinstance(result.get('campaign'), dict) else {}
                fields = ('run_id', 'suite', 'suite_version', 'model', 'completed', 'total',
                          'correct', 'format_errors', 'run_state')
                payload = {
                    'schema': 'argos-monitor-campaign/1', 'available': bool(self.server.proctor_campaign),
                    'active': state.get('active'), 'phase': state.get('phase'),
                    'elapsed_seconds': state.get('elapsed_seconds'), 'model': state.get('model'),
                    'measurement_suite': state.get('measurement_suite'),
                    'assistant_ready': state.get('assistant_ready'),
                    'failure_code': state.get('failure_code'), 'failure_stage': state.get('failure_stage'),
                    'progress': {key: progress.get(key) for key in
                                 ('stage', 'turn', 'total', 'saved_evaluation_count', 'audit_status')},
                    'current': {key: current.get(key) for key in ('run_id', 'item_id', 'category', 'state')},
                    'evaluation_runs': [{key: row.get(key) for key in fields if key in row}
                                        for row in progress.get('evaluation_runs', [])
                                        if isinstance(row, dict)],
                    'result': {key: result.get(key) for key in ('status', 'failure_code')},
                    'result_campaign': {key: campaign.get(key) for key in
                                        ('outcome', 'audit_status', 'saved_evaluation_ids', 'missing')},
                }
                self.reply(200, payload)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                self.reply(503, {'error': 'Campaign status unavailable'})
            return
        if path == '/api/monitor/results':
            try:
                from argoslive import proctor_match
                fields = ('run_id', 'created', 'suite', 'suite_version', 'state',
                          'complete', 'correct', 'scored_total')
                rounds = [{key: row.get(key) for key in fields}
                          for row in proctor_match.recent(self.server.store, limit=6)]
                self.reply(200, {'schema': 'argos-monitor-results/1', 'rounds': rounds})
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                self.reply(503, {'error': 'Saved results unavailable'})
            return
        self.reply(404, {'error': 'Unknown read-only monitor route'})

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.reply(405, {'error': 'Monitor is read-only'})

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
