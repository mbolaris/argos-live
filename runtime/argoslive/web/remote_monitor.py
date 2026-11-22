"""Private, read-only monitor endpoint for Tailscale Serve."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from argoslive.web import telemetry

ASSETS = Path(__file__).with_name('static')
PORT = 8766


def evaluation_settings(store, run_id):
    """Project recorded evaluation controls, never prompts or configuration secrets."""
    try:
        run = store.load(run_id)
        settings = run.get('settings') or {}
        model = settings.get('model') or {}
        metadata = model.get('metadata') or {}
        generation = settings.get('configured_generation') or {}
        scopes = {}
        allowed = {'temperature', 'topP', 'maxTokens', 'seed', 'num_ctx', 'num_predict', 'think', 'thinking',
                   'contextTokens', 'thinkingDefault', 'top_k', 'top_p', 'min_p'}
        for name in ('defaults', 'default_params', 'model_params', 'agent_params', 'agent_model_params', 'provider_model_params'):
            values = generation.get(name)
            if not isinstance(values, dict):
                continue
            safe = {}
            for key, value in values.items():
                if key not in allowed:
                    continue
                if type(value) is bool or type(value) in (int, float) and math.isfinite(value):
                    safe[key] = value
                elif key in ('think', 'thinking', 'thinkingDefault') and value in ('off', 'none', 'disabled', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'adaptive', 'ultra'):
                    safe[key] = value
            if safe:
                scopes[name] = safe
        return {'run_id': run.get('id'), 'suite_version': run.get('suite_version'), 'model': run.get('model'),
                'context_window': metadata.get('contextWindow') if type(metadata.get('contextWindow')) is int else None,
                'max_tokens': metadata.get('maxTokens') if type(metadata.get('maxTokens')) is int else None,
                'execution_path': 'isolated; tools denied' if settings.get('execution_path') == 'openclaw embedded; ephemeral state; tools denied; v2' else 'see run record',
                'configured_generation': scopes}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


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
        if isinstance(login, str) and login and len(login) <= 254:
            return login
        # Newer Tailscale status JSON can omit Self.UserProfile even while the
        # node is authenticated. Resolve the local node through whois instead
        # of failing closed with a permanent None identity.
        addresses = (value.get('Self') or {}).get('TailscaleIPs') or value.get('TailscaleIPs') or []
        for address in addresses:
            if not isinstance(address, str) or not address:
                continue
            whois = subprocess.run([executable, 'whois', '--json', address],
                                   capture_output=True, text=True, timeout=4, check=True)
            identity = json.loads(whois.stdout)
            profile = identity.get('UserProfile') or {}
            login = profile.get('LoginName')
            if isinstance(login, str) and login and len(login) <= 254:
                return login
        return None
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return None


class RemoteMonitorServer(ThreadingHTTPServer):
    """Only monitor assets and read-only projections; never the operator UI."""
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, *, proctor_campaign, store, startup=None, host='127.0.0.1', port=PORT,
                 allowed_login=None):
        if host != '127.0.0.1' or type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Remote monitor must bind to loopback')
        self.proctor_campaign = proctor_campaign
        self.startup = startup
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
            sample = telemetry.snapshot()
            try:
                state = self.server.startup.snapshot() if self.server.startup else {}
                metrics = state.get('metrics') or {}
                sample['assistant'] = {'phase': state.get('phase'), 'model': state.get('model'),
                    'generation_tokens_per_second': metrics.get('generation_tokens_per_second'),
                    'time_to_first_token_seconds': metrics.get('time_to_first_token_seconds')}
            except (OSError, ValueError, TypeError, AttributeError):
                sample['assistant'] = None
            self.reply(200, sample)
            return
        if path == '/api/monitor/campaign':
            try:
                state = (self.server.proctor_campaign.snapshot()
                         if self.server.proctor_campaign else {})
                progress = state.get('progress') if isinstance(state.get('progress'), dict) else {}
                current = progress.get('current') if isinstance(progress.get('current'), dict) else {}
                result = state.get('result') if isinstance(state.get('result'), dict) else {}
                campaign = result.get('campaign') if isinstance(result.get('campaign'), dict) else {}
                runs = progress.get('evaluation_runs') if isinstance(progress.get('evaluation_runs'), list) else []
                latest_run = next((row.get('run_id') for row in reversed(runs) if isinstance(row, dict) and isinstance(row.get('run_id'), str)), None)
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
                                 ('stage', 'turn', 'total', 'saved_evaluation_count', 'audit_status', 'current_elapsed_seconds')},
                    'steps': [{key: step.get(key) for key in ('tool', 'status', 'step_status', 'resolution', 'passed')}
                              for step in progress.get('campaign_steps', [])[-12:] if isinstance(step, dict)],
                    'recorded_settings': evaluation_settings(self.server.store, latest_run) if latest_run else None,
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
                          'complete', 'correct', 'scored_total', 'partitions', 'model', 'median_latency_seconds')
                rounds = [{key: row.get(key) for key in fields}
                          for row in proctor_match.recent(self.server.store, limit=6)]
                for row in rounds:
                    row['recorded_settings'] = evaluation_settings(self.server.store, row.get('run_id'))
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
