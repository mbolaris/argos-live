#!/usr/bin/env python3
"""Loopback-only Debian Snapshot proxy with signed-hash index recovery.

Debootstrap requests uncompressed Packages indexes.  If Snapshot returns a
transient server error, the current Debian mirror may still have the matching
compressed index.  This proxy serves that copy only after verifying the
Snapshot InRelease signature and the exact SHA-256 listed in its cleartext.
All other requests continue to the pinned Snapshot URL, so package sources and
security-suite selection remain unchanged.
"""

import argparse
import bz2
import gzip
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import lzma
import os
from pathlib import PurePosixPath
import re
import shutil
import subprocess
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


ARCHIVES = {
    "debian": "https://deb.debian.org/debian",
    "debian-security": "https://security.debian.org/debian-security",
}
SNAPSHOT_ARCHIVE = "https://snapshot.debian.org/archive"
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
INDEX_PATH = re.compile(
    r"^dists/(?P<suite>[A-Za-z0-9.+-]+)/"
    r"(?P<index>(?:main|contrib|non-free|non-free-firmware)/"
    r"binary-[A-Za-z0-9-]+/Packages(?:\.(?:xz|gz|bz2))?)$"
)


def read_response(url, timeout=45):
    request = Request(url, headers={"User-Agent": "argos-live-pinned-build/1"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("upstream response exceeds the size limit")
        return body


def snapshot_url(archive, snapshot, relative):
    return f"{SNAPSHOT_ARCHIVE}/{archive}/{snapshot}/{relative}"


def index_sha256(inrelease, index_path):
    """Return a SHA-256 and size only from the signed cleartext payload."""
    text = inrelease.decode("utf-8", errors="strict")
    begin = text.find("-----BEGIN PGP SIGNED MESSAGE-----")
    signature = text.find("-----BEGIN PGP SIGNATURE-----")
    if begin != 0 or signature < 0:
        raise ValueError("Snapshot InRelease is not clear-signed")
    header_end = text.find("\n\n")
    if header_end < 0 or header_end >= signature:
        raise ValueError("Snapshot InRelease has no cleartext body")
    payload = text[header_end + 2:signature]
    payload = "\n".join(
        line[2:] if line.startswith("- ") else line
        for line in payload.splitlines()
    )
    match = re.search(
        r"(?ms)^SHA256:\s*\n(?P<records>.*?)(?=^[A-Za-z][A-Za-z0-9-]*:|\Z)",
        payload,
    )
    if not match:
        raise ValueError("Snapshot InRelease has no SHA256 section")
    for line in match.group("records").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == index_path:
            if not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) or not parts[1].isdigit():
                raise ValueError("Snapshot InRelease index record is malformed")
            return parts[0].lower(), int(parts[1])
    raise ValueError("Snapshot InRelease does not list the requested Packages index")


def verify_inrelease(inrelease, keyring):
    """Require a valid Debian archive signature before using Release hashes."""
    if not keyring or not os.path.isfile(keyring):
        raise ValueError("pinned Debian archive keyring is unavailable")
    with tempfile.NamedTemporaryFile(prefix="argos-inrelease-", delete=False) as stream:
        path = stream.name
        stream.write(inrelease)
    try:
        result = subprocess.run(
            ["gpgv", "--keyring", keyring, path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        if result.returncode:
            raise ValueError("Snapshot InRelease signature verification failed")
    finally:
        os.unlink(path)


def decode_index_candidate(path, body):
    if path.endswith(".xz"):
        return lzma.decompress(body)
    if path.endswith(".gz"):
        return gzip.decompress(body)
    if path.endswith(".bz2"):
        return bz2.decompress(body)
    return body


class SnapshotIndexFallback:
    def __init__(self, keyring, fetch=read_response, verify=verify_inrelease):
        self.keyring = keyring
        self.fetch = fetch
        self.verify = verify

    def recover(self, archive, snapshot, relative):
        """Fetch a byte-identical Packages index, or raise without bypassing pins."""
        match = INDEX_PATH.fullmatch(relative)
        if archive not in ARCHIVES or not match:
            raise ValueError("request is not a supported Debian binary Packages index")
        suite = match.group("suite")
        index_path = match.group("index")
        release = self.fetch(snapshot_url(archive, snapshot, f"dists/{suite}/InRelease"))
        self.verify(release, self.keyring)
        expected_hash, expected_size = index_sha256(release, index_path)

        candidate_base = ARCHIVES[archive]
        candidate_paths = [index_path]
        if not index_path.endswith((".xz", ".gz", ".bz2")):
            candidate_paths.extend(index_path + suffix for suffix in (".xz", ".gz", ".bz2"))
        errors = []
        for candidate_path in candidate_paths:
            try:
                body = self.fetch(f"{candidate_base}/dists/{suite}/{candidate_path}")
                decoded = decode_index_candidate(candidate_path, body)
                digest = hashlib.sha256(decoded).hexdigest()
                if digest != expected_hash or len(decoded) != expected_size:
                    errors.append(f"{candidate_path} did not match the pinned Release hash")
                    continue
                return decoded
            except (HTTPError, URLError, OSError, EOFError, lzma.LZMAError, gzip.BadGzipFile, ValueError) as exc:
                if isinstance(exc, HTTPError):
                    exc.close()
                errors.append(f"{candidate_path}: {exc}")
        raise ValueError("no current-mirror index matched the signed Snapshot hash: " + "; ".join(errors))


def parse_route(request_path, debian_snapshot, security_snapshot):
    parsed = urlsplit(request_path)
    if parsed.query or parsed.fragment:
        raise ValueError("query and fragment are not supported")
    path = unquote(parsed.path).lstrip("/")
    parts = PurePosixPath(path).parts
    if len(parts) < 4 or parts[0] != "archive":
        raise ValueError("request is outside the pinned archive roots")
    archive = parts[1]
    snapshot = parts[2]
    expected = {
        "debian": debian_snapshot,
        "debian-security": security_snapshot,
    }.get(archive)
    if expected is None or snapshot != expected:
        raise ValueError("request is not for a configured pinned Snapshot")
    relative = "/".join(parts[3:])
    if any(part in (".", "..") for part in PurePosixPath(relative).parts):
        raise ValueError("path traversal is not allowed")
    return archive, snapshot, relative


class SnapshotHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_HEAD(self):
        self.handle_request(send_body=False)

    def do_GET(self):
        self.handle_request(send_body=True)

    def handle_request(self, send_body):
        try:
            archive, snapshot, relative = parse_route(
                self.path,
                self.server.debian_snapshot,
                self.server.security_snapshot,
            )
            target = snapshot_url(archive, snapshot, relative)
            try:
                body = self.server.fetch(target)
                status = 200
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if status < 500:
                    self.respond(status, b"Snapshot request failed\n", send_body)
                    return
                body = self.server.recover_index(archive, snapshot, relative)
                status = 200
                print(
                    f"Hash-verified Snapshot index fallback: {archive}/{snapshot}/{relative}",
                    flush=True,
                )
            self.respond(status, body, send_body)
        except (HTTPError, URLError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Snapshot proxy request failed: {type(exc).__name__}: {exc}", flush=True)
            self.respond(503, b"Pinned Snapshot source unavailable\n", send_body)

    def respond(self, status, body, send_body):
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debian-snapshot", required=True)
    parser.add_argument("--security-snapshot", required=True)
    parser.add_argument("--keyring", required=True)
    parser.add_argument("--port-file", required=True)
    args = parser.parse_args()
    for snapshot in (args.debian_snapshot, args.security_snapshot):
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", snapshot):
            parser.error("snapshot values must be pinned UTC timestamps")
    if not os.path.isfile(args.keyring):
        parser.error("pinned Debian archive keyring does not exist")

    fallback = SnapshotIndexFallback(args.keyring)
    server = ThreadingHTTPServer(("127.0.0.1", 0), SnapshotHandler)
    server.daemon_threads = True
    server.debian_snapshot = args.debian_snapshot
    server.security_snapshot = args.security_snapshot
    server.fetch = read_response
    server.recover_index = fallback.recover
    temporary = f"{args.port_file}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="ascii") as stream:
        stream.write(str(server.server_address[1]) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, args.port_file)
    print(f"Pinned Snapshot proxy listening on 127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
