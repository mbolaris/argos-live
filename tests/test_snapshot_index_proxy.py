import hashlib
import importlib.util
import lzma
from pathlib import Path
import unittest
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "snapshot_index_proxy", ROOT / "scripts" / "snapshot-index-proxy.py"
)
proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proxy)
RESCUE_SPEC = importlib.util.spec_from_file_location(
    "rescue_snapshot_package_cache", ROOT / "scripts" / "rescue-snapshot-package-cache.py"
)
rescue = importlib.util.module_from_spec(RESCUE_SPEC)
RESCUE_SPEC.loader.exec_module(rescue)


def inrelease_for(index_path, body):
    digest = hashlib.sha256(body).hexdigest()
    record = f"{digest} {len(body)} {index_path}\n"
    return (
        "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n"
        "Origin: Debian\nSHA256:\n " + record +
        "-----BEGIN PGP SIGNATURE-----\nfake signature\n-----END PGP SIGNATURE-----\n"
    ).encode()


class SnapshotIndexProxyTests(unittest.TestCase):
    def test_missing_uncompressed_index_uses_exact_xz_bytes_from_current_mirror(self):
        relative = "dists/trixie/contrib/binary-amd64/Packages"
        body = b"Package: demo\nVersion: 1\n\n"
        release = inrelease_for("contrib/binary-amd64/Packages", body)
        compressed = lzma.compress(body)
        urls = {
            proxy.snapshot_url("debian", "20261011T000000Z", "dists/trixie/InRelease"): release,
            "https://deb.debian.org/debian/dists/trixie/contrib/binary-amd64/Packages.xz": compressed,
        }

        def fetch(url):
            if url in urls:
                return urls[url]
            raise HTTPError(url, 404, "not found", {}, None)

        fallback = proxy.SnapshotIndexFallback(
            "/unused/keyring.gpg", fetch=fetch, verify=lambda _release, _keyring: None
        )
        self.assertEqual(fallback.recover("debian", "20261011T000000Z", relative), body)

    def test_rejects_current_index_that_does_not_match_pinned_hash(self):
        relative = "dists/trixie/contrib/binary-amd64/Packages"
        release = inrelease_for("contrib/binary-amd64/Packages", b"pinned index")
        urls = {
            proxy.snapshot_url("debian", "20261011T000000Z", "dists/trixie/InRelease"): release,
            "https://deb.debian.org/debian/dists/trixie/contrib/binary-amd64/Packages.xz": lzma.compress(b"different index"),
        }

        def fetch(url):
            if url in urls:
                return urls[url]
            raise HTTPError(url, 404, "not found", {}, None)

        fallback = proxy.SnapshotIndexFallback(
            "/unused/keyring.gpg", fetch=fetch, verify=lambda _release, _keyring: None
        )
        with self.assertRaisesRegex(ValueError, "did not match the pinned Release hash"):
            fallback.recover("debian", "20261011T000000Z", relative)

    def test_rejects_fallback_when_signature_verification_fails(self):
        relative = "dists/trixie/contrib/binary-amd64/Packages"
        release = inrelease_for("contrib/binary-amd64/Packages", b"pinned index")
        urls = {
            proxy.snapshot_url("debian", "20261011T000000Z", "dists/trixie/InRelease"): release,
        }

        def fetch(url):
            if url in urls:
                return urls[url]
            raise AssertionError("index candidate must not be fetched before signature validation")

        def reject_signature(_release, _keyring):
            raise ValueError("signature rejected")

        fallback = proxy.SnapshotIndexFallback(
            "/unused/keyring.gpg", fetch=fetch, verify=reject_signature
        )
        with self.assertRaisesRegex(ValueError, "signature rejected"):
            fallback.recover("debian", "20261011T000000Z", relative)

    def test_fallback_is_limited_to_the_two_configured_snapshot_roots(self):
        self.assertEqual(
            proxy.parse_route(
                "/archive/debian/20261011T000000Z/dists/trixie/InRelease",
                "20261011T000000Z",
                "20261011T000000Z",
            ),
            ("debian", "20261011T000000Z", "dists/trixie/InRelease"),
        )
        for path in (
            "/archive/debian/20261012T000000Z/dists/trixie/InRelease",
            "/archive/other/20261011T000000Z/dists/trixie/InRelease",
            "/archive/debian/20261011T000000Z/dists/../pool/package.deb",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                proxy.parse_route(path, "20261011T000000Z", "20261011T000000Z")

    def test_package_cache_rescue_recognizes_the_loopback_proxy_path(self):
        result = rescue.failed_snapshot_urls(
            "E: Couldn't download "
            "http://127.0.0.1:43125/archive/debian/20261011T000000Z/"
            "pool/main/d/demo/demo_1_amd64.deb"
        )
        self.assertEqual(
            result,
            [
                (
                    "debian",
                    "20261011T000000Z",
                    "pool/main/d/demo/demo_1_amd64.deb",
                    "pool/main/d/demo/demo_1_amd64.deb",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
