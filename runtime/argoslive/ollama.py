"""Stdlib Ollama API client. No daemon startup, configuration mutation or logging."""
import json
from http.client import HTTPException
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class OllamaError(RuntimeError):
    pass


class NotRunning(OllamaError):
    pass


class ModelMissing(OllamaError):
    pass


class Cancelled(OllamaError):
    pass


class Interrupted(OllamaError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    """Callbacks receive decoded stream events; cancellation uses Event.is_set().

    Cancellation is checked before requests and between reads/callbacks. A stalled
    read is bounded by timeout, not immediately interruptible. Closing a pull stream
    does not promise that Ollama has stopped shared server-side download activity.
    """
    def __init__(self, base_url='http://127.0.0.1:11434', *, timeout=30,
                 clock=time.monotonic):
        url = urlsplit(base_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.path not in ('', '/')):
            raise ValueError('Ollama URL must be an HTTP(S) origin without credentials')
        _ = url.port  # Validate malformed ports before opening a request.
        if timeout <= 0:
            raise ValueError('Timeout must be positive')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.clock = clock
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    @staticmethod
    def _cancel(cancel):
        if cancel is not None and cancel.is_set():
            raise Cancelled('Ollama operation cancelled')

    def _open(self, path, payload=None):
        request = Request(self.base_url + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Content-Type': 'application/json'})
        try:
            return self.opener.open(request, timeout=self.timeout)
        except HTTPError as exc:
            exc.close()
            if exc.code == 404 and path in ('/api/show', '/api/generate', '/api/chat'):
                raise ModelMissing('Requested model is missing') from exc
            raise OllamaError(f'Ollama HTTP failure ({exc.code})') from exc
        except (URLError, OSError, HTTPException) as exc:
            raise NotRunning('Ollama is not reachable; check its service and endpoint') from exc

    @staticmethod
    def _decode(raw):
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise OllamaError('Invalid JSON from Ollama') from exc
        if not isinstance(event, dict):
            raise OllamaError('Expected an Ollama JSON object')
        if 'error' in event:
            # Backend messages may include paths, prompts or upstream credentials.
            raise OllamaError('Ollama reported an operation error')
        return event

    def _json(self, path, payload=None):
        with self._open(path, payload) as response:
            try:
                raw = response.read(4 * 1024**2 + 1)
            except (OSError, ValueError, HTTPException) as exc:
                raise Interrupted('Ollama response interrupted') from exc
            if len(raw) > 4 * 1024**2:
                raise OllamaError('Ollama response exceeds size limit')
            return self._decode(raw)

    def version(self):
        return self._json('/api/version').get('version')

    def list(self):
        return self._json('/api/tags')

    def show(self, model):
        return self._json('/api/show', {'model': model})

    def ps(self):
        return self._json('/api/ps')

    def unload(self, model):
        return self._json('/api/generate', {'model': model, 'keep_alive': 0, 'stream': False})

    def _stream(self, path, payload, callback, cancel, *, pull=False):
        self._cancel(cancel)
        started = self.clock()
        first_token = None
        text = []
        thinking = []
        with self._open(path, payload) as response:
            while True:
                self._cancel(cancel)
                try:
                    line = response.readline(4 * 1024**2 + 1)
                except (OSError, ValueError, HTTPException) as exc:
                    self._cancel(cancel)
                    raise Interrupted('Ollama stream interrupted') from exc
                self._cancel(cancel)
                if not line:
                    raise Interrupted('Ollama stream ended before completion')
                if len(line) > 4 * 1024**2:
                    raise OllamaError('Ollama stream event exceeds size limit')
                if not line.strip():
                    continue
                event = self._decode(line)
                message = event.get('message', {})
                if not isinstance(message, dict):
                    raise OllamaError('Invalid Ollama message')
                content = event.get('response', message.get('content', ''))
                reason = event.get('thinking', message.get('thinking', ''))
                if not isinstance(content, str) or not isinstance(reason, str):
                    raise OllamaError('Invalid Ollama text chunk')
                if first_token is None and (content or reason):
                    first_token = self.clock() - started
                text.append(content)
                thinking.append(reason)
                terminal = event.get('status') == 'success' if pull else event.get('done') is True
                if callback is not None:
                    callback(event)
                self._cancel(cancel)
                if terminal:
                    return {'final': event, 'text': ''.join(text), 'thinking': ''.join(thinking),
                            'time_to_first_token_seconds': first_token,
                            'elapsed_seconds': self.clock() - started}

    def pull(self, model, *, callback=None, cancel=None):
        return self._stream('/api/pull', {'model': model, 'stream': True},
                            callback, cancel, pull=True)

    def generate(self, model, prompt, *, options=None, system=None, think=None, keep_alive=None,
                 callback=None, cancel=None):
        payload = {'model': model, 'prompt': prompt, 'stream': True, 'options': options or {}}
        if system is not None:
            payload['system'] = system
        if think is not None:
            payload['think'] = think
        if keep_alive is not None:
            payload['keep_alive'] = keep_alive
        return self._stream('/api/generate', payload, callback, cancel)

    def chat(self, model, messages, *, options=None, system=None, think=None, keep_alive=None,
             callback=None, cancel=None):
        payload = {'model': model, 'messages': messages, 'stream': True, 'options': options or {}}
        if system is not None:
            payload['system'] = system
        if think is not None:
            payload['think'] = think
        if keep_alive is not None:
            payload['keep_alive'] = keep_alive
        return self._stream('/api/chat', payload, callback, cancel)
