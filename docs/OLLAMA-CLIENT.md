# Ollama client foundation

`runtime/argoslive/ollama.py` implements the B2 stdlib API client for the pinned Ollama 0.35.0. Fields were checked against [that version's API types](https://github.com/ollama/ollama/blob/v0.35.0/api/types.go). It is a library foundation; dashboard/download-job wiring and benchmark orchestration remain separate backlog items.

`Client()` defaults to `http://127.0.0.1:11434`. It supports `version`, `list`, `show`, `ps`, `unload`, `pull`, `generate` and `chat`. Metadata and final timing fields remain raw backend data, including nanosecond durations. Unknown fields are not invented. Streaming methods return accumulated text/thinking, the final event, elapsed seconds and time to first token measured with a monotonic clock. First token includes reasoning text, excludes empty events, and stays null if no text arrives.

Progress callbacks receive the original pull events with digest/total/completed fields. Cancellation accepts a threading Event: it closes the response and raises Cancelled when observed before the request or between reads/callbacks. A stalled socket read is bounded by the configured timeout; cancellation is not an immediate interrupt of that read. Disconnecting a pull does not establish whether shared server-side download activity stopped. Durable job state, resume policy and model-integrity checks belong to MD4, not this client.

An ended stream without a success/done event raises Interrupted. Unreachable service, missing models and HTTP failures have separate error types. Server error bodies are not logged or included in exception messages. Callbacks and returned text remain caller-owned private data. The client does not start a daemon, change config, select storage, infer readiness, or automatically unload a model after generation.

Configured URLs must be HTTP(S) origins without embedded credentials, paths or query strings. Environment proxies and redirects are disabled so local requests cannot silently move to another service. No listener or firewall is created. Keep Live's inference service on loopback.

Tests use authored v0.35.0 protocol fixtures served from a temporary loopback HTTP server. They cover metadata, progress, cancellation, chat/generation timing, unload, malformed replies, operation errors and interrupted streams. They do not establish actual Ollama or physical GPU acceptance.
