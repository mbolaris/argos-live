"""Ed25519 through the system OpenSSL executable; no Python crypto dependencies."""
import base64
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def _run(executable, arguments):
    result = subprocess.run([executable, *arguments], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=15)
    if result.returncode:
        # Tool errors can contain private filesystem paths; keep public errors generic.
        raise ValueError('OpenSSL operation failed')
    return result.stdout


def generate_key(path, *, executable='openssl'):
    """Host provisioning, once per installation. Refuses overwrite and linked paths."""
    path = Path(path)
    if not shutil.which(executable):
        raise ValueError('System OpenSSL is required for Ed25519')
    if path.is_symlink():
        raise ValueError('Refusing a linked signing key')
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if os.name != 'nt' and path.parent.stat().st_mode & 0o077:
        raise ValueError('Signing keys require a private directory')
    key = _run(executable, ['genpkey', '-algorithm', 'ED25519'])
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(key)
        stream.flush()
        os.fsync(stream.fileno())


class Ed25519Signer:
    def __init__(self, key_path, *, executable='openssl'):
        path = Path(key_path)
        if path.is_symlink() or (os.name != 'nt' and path.stat().st_mode & 0o077):
            raise ValueError('Signing key must be private and unlinked')
        self.key_path, self.executable = path, executable
        self.public_key_der = _run(executable, ['pkey', '-in', str(path), '-pubout', '-outform', 'DER'])
        # SubjectPublicKeyInfo encoding for Ed25519. Reject other key algorithms.
        if len(self.public_key_der) != 44 or self.public_key_der[:12].hex() != '302a300506032b6570032100':
            raise ValueError('An Ed25519 private key is required')
        self.key_id = hashlib.sha256(self.public_key_der).hexdigest()

    def sign(self, payload):
        with tempfile.TemporaryDirectory(prefix='argos-proctor-sign-') as directory:
            message = Path(directory) / 'payload'
            message.write_bytes(payload)
            signature = _run(self.executable, ['pkeyutl', '-sign', '-rawin', '-inkey', str(self.key_path), '-in', str(message)])
        if len(signature) != 64:
            raise ValueError('Invalid Ed25519 signature length')
        return {'algorithm': 'Ed25519', 'key_id': self.key_id,
                'sig_base64': base64.b64encode(signature).decode('ascii')}


def verify_envelope(envelope, trusted_public_key_der, *, executable='openssl'):
    """Verify using an independently trusted public key, never a key supplied by the envelope."""
    try:
        if (not isinstance(envelope, dict) or not isinstance(trusted_public_key_der, bytes)
                or not isinstance(envelope.get('signature'), dict)
                or not isinstance(envelope.get('payload_json'), str)):
            return False
        if envelope['envelope_version'] != 'argos.proctor.envelope.v1':
            return False
        metadata = envelope['signature']
        if metadata['algorithm'] != 'Ed25519' or metadata['key_id'] != hashlib.sha256(trusted_public_key_der).hexdigest():
            return False
        signature = base64.b64decode(metadata['sig_base64'], validate=True)
        if len(signature) != 64 or len(trusted_public_key_der) != 44 or trusted_public_key_der[:12].hex() != '302a300506032b6570032100':
            return False
        payload = envelope['payload_json'].encode('utf-8')
        if len(payload) > 4 * 1024 * 1024:
            return False
        with tempfile.TemporaryDirectory(prefix='argos-proctor-verify-') as directory:
            root = Path(directory)
            (root / 'key.der').write_bytes(trusted_public_key_der)
            (root / 'payload').write_bytes(payload)
            (root / 'signature').write_bytes(signature)
            _run(executable, ['pkeyutl', '-verify', '-pubin', '-keyform', 'DER', '-inkey', str(root / 'key.der'),
                              '-rawin', '-in', str(root / 'payload'), '-sigfile', str(root / 'signature')])
        return True
    except (KeyError, TypeError, ValueError, UnicodeError):
        return False
