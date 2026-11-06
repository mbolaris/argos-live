#!/usr/bin/env python3
"""Fill live-build's package cache from Debian's current mirror, hash-locked to Snapshot metadata.

Snapshot occasionally returns transient 5xx errors for individual .deb files. A package
with the same pool path can still be present on deb.debian.org. This helper only caches
such a copy when the package metadata already loaded from the signed Snapshot indexes
matches its identity, filename, and SHA-256 exactly. APT continues to use the pinned
Snapshot indexes; fallback bytes are checked against the selected package record.
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen


SNAPSHOT_URL = re.compile(
    r"https://snapshot\.debian\.org/archive/"
    r"(debian|debian-security)/([0-9]{8}T[0-9]{6}Z)/(pool/[^\s'\"<>]+?\.deb)"
)
ARCHIVES = {"debian", "debian-security"}


def fields(paragraph):
    result = {}
    for line in paragraph.splitlines():
        if line[:1].isspace():
            continue
        key, sep, value = line.partition(":")
        if sep:
            result[key] = value.strip()
    return result


def dpkg_fields(path):
    completed = subprocess.run(
        ["dpkg-deb", "-f", str(path), "Package", "Version", "Architecture"],
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    values = fields(completed.stdout)
    required = ("Package", "Version", "Architecture")
    if any(not values.get(key) for key in required):
        raise ValueError("package identity fields are incomplete")
    return {key: values[key] for key in required}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_metadata(chroot, identity, pool_path):
    completed = subprocess.run(
        ["chroot", str(chroot), "apt-cache", "show", identity["Package"]],
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    matches = []
    for paragraph in re.split(r"\n\s*\n", completed.stdout):
        record = fields(paragraph)
        if all(record.get(key) == identity.get(key) for key in identity):
            if record.get("Filename") == pool_path and re.fullmatch(
                r"[0-9a-fA-F]{64}", record.get("SHA256", "")
            ):
                matches.append(record)
    distinct = {(record["Filename"], record["SHA256"].lower()) for record in matches}
    if len(distinct) != 1:
        raise ValueError("exact package is not uniquely present in the trusted Snapshot indexes")
    return matches[0]


def fetch(url, destination):
    last_error = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "argos-live-pinned-build/1"})
            with urlopen(request, timeout=45) as response, destination.open("wb") as output:
                if response.status != 200:
                    raise ValueError(f"fallback mirror returned HTTP {response.status}")
                shutil.copyfileobj(response, output)
            return
        except (HTTPError, URLError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise last_error


def rescue(log, chroot, cache_root):
    urls = []
    for line in log.read_text(errors="replace").splitlines():
        if not re.search(r"(?:Failed to fetch|Couldn't download|Unable to fetch)", line, re.I):
            continue
        for match in SNAPSHOT_URL.finditer(line):
            archive, snapshot, encoded_pool_path = match.groups()
            if archive not in ARCHIVES:
                continue
            pool_path = unquote(encoded_pool_path)
            if not pool_path.startswith("pool/") or ".." in Path(pool_path).parts:
                continue
            item = (archive, snapshot, encoded_pool_path, pool_path)
            if item not in urls:
                urls.append(item)

    if not urls:
        print("No failed Snapshot package URLs found for cache rescue.")
        return 0

    rescued = 0
    with tempfile.TemporaryDirectory(prefix="argos-snapshot-cache-") as temporary:
        temp_root = Path(temporary)
        for index, (archive, _snapshot, encoded_path, pool_path) in enumerate(urls):
            url = f"https://deb.debian.org/{archive}/{encoded_path}"
            candidate = temp_root / f"package-{index}.deb"
            try:
                fetch(url, candidate)
                identity = dpkg_fields(candidate)
                trusted = snapshot_metadata(chroot, identity, pool_path)
                digest = sha256(candidate)
                if digest.lower() != trusted["SHA256"].lower():
                    raise ValueError("fallback package hash differs from trusted Snapshot metadata")
                filename = unquote(encoded_path.rsplit("/", 1)[-1])
                version_in_filename = re.sub(r"^[0-9]+:", "", identity["Version"])
                expected_filename = (
                    f"{identity['Package']}_{version_in_filename}_"
                    f"{identity['Architecture']}.deb"
                )
                if filename != expected_filename:
                    raise ValueError("fallback filename disagrees with package identity")
                for cache_name in ("packages.binary", "packages.chroot"):
                    destination_dir = cache_root / cache_name
                    destination_dir.mkdir(parents=True, exist_ok=True)
                    destination = destination_dir / filename
                    if destination.exists():
                        existing = sha256(destination)
                        if existing != digest:
                            raise ValueError(f"conflicting package already exists in {cache_name}")
                    else:
                        shutil.copyfile(candidate, destination)
                rescued += 1
                print(f"Snapshot-hash-verified cache entry: {filename} sha256={digest}")
            except (HTTPError, URLError, OSError, subprocess.CalledProcessError, ValueError) as exc:
                print(f"Cache rescue unavailable for {encoded_path}: {exc}")

    print(f"Added {rescued} Snapshot-hash-verified package cache entr{'y' if rescued == 1 else 'ies'}.")
    return rescued


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("chroot", type=Path)
    parser.add_argument("cache_root", type=Path)
    args = parser.parse_args()
    if not args.log.is_file() or not args.chroot.is_dir():
        parser.error("build log and live-build chroot must exist")
    if not os.geteuid() == 0:
        parser.error("must run as root inside the disposable CI builder")
    rescue(args.log, args.chroot, args.cache_root)


if __name__ == "__main__":
    main()
