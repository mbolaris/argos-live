"""Loopback protocol fixtures: reuse TIME_WAIT, never share a live listener.

Linux SO_REUSEADDR permits a stopped fixture's TCP tuples to drain while a new
fixture binds. SO_REUSEPORT would admit simultaneous listeners and stays off.
Every caller separately requires a disposable, unprivileged hosted runner.
"""
from http.server import ThreadingHTTPServer


class SyntheticHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    allow_reuse_port = False
