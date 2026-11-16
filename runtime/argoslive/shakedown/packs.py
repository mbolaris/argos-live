"""Benchmark packs: licence-gated, hash-verified subsets of public benchmarks.

The repository ships a manifest per pack (`argos-benchmark-pack/1`): where the
upstream files live, their pinned revision and SHA-256 values, the licence
record, the fixed item-ID list and its lap slices. It never ships benchmark
questions. The owner downloads the pinned files from their original source
after reading the licence record; the files are verified by hash before every
use and an adapter turns them into an in-memory `argos-ability-suite/1` form.

The only network call in this module is the owner-started download in
`Downloads`. Nothing is uploaded.
"""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys
import tarfile
import threading
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from .. import ability, storage
from ..pull_jobs import Queue, WorkerBusy, read_json, stamp, worker_lock, write_json

SCHEMA = 'argos-benchmark-pack/1'
RECEIPT_SCHEMA = 'argos-benchmark-pack-receipt/1'
JOB_SCHEMA = 'argos-benchmark-pack-pull/1'
DATA = Path(__file__).resolve().parents[1] / 'data' / 'shakedown' / 'packs'
SUITE_PREFIX = 'pack-'
SIZES = ('quick', 'standard', 'full')
# Sources a shipped manifest may point at. A redirect may leave these hosts
# (large files are served from a CDN); the pinned SHA-256 is what is trusted.
ALLOWED_HOSTS = ('huggingface.co', 'raw.githubusercontent.com', 'github.com',
                 'people.eecs.berkeley.edu')
MANIFEST_LIMIT = 1024 ** 2
MAX_FILES = 16
MAX_FILE_BYTES = 2 * 1024 ** 3
MAX_ITEMS = 1000
PROMPT_LIMIT = 16384
SPACE_MARGIN = 64 * 1024 ** 2
CHUNK = 1024 ** 2
JOB_STATES = ('queued', 'downloading', 'verifying', 'ready', 'failed', 'cancelled')
FOOTNOTES = ('subset', 'public', 'not the official score')

_PACK_ID = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
_VERSION = re.compile(r'\d+\.\d+\.\d+')
_REVISION = re.compile(r'[0-9a-f]{40}')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_FILE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_ITEM_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,95}')
_LICENCE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9.+-]{0,63}')
_ADAPTER = re.compile(r'[a-z][a-z0-9-]{0,63}')
_MANIFEST_KEYS = {'schema', 'pack', 'name', 'label', 'version', 'adapter', 'upstream', 'files',
                  'licences', 'gated', 'terms_url', 'items', 'slices'}


class PackError(ValueError):
    """A pack cannot be used; the message is safe to show the owner."""


class PackNotDownloaded(PackError):
    """The pinned files, or the owner's licence receipt, are not on this machine."""


class PackRefused(PackError):
    """A file on disk or on the wire is not the pinned file. The message names it."""


class Cancelled(Exception):
    """The owner cancelled a download."""


def _text(value, limit):
    return (isinstance(value, str) and 1 <= len(value) <= limit and value == value.strip()
            and not any(ord(char) < 32 for char in value))


def _https(value, *, hosts=None):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048 or any(char.isspace() for char in value):
        return False
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == 'https' and bool(parts.hostname) and parts.username is None
            and parts.password is None and port is None and not parts.fragment
            and (hosts is None or parts.hostname in hosts))


def _subsequence(part, whole):
    """True when `part` keeps the order of `whole` and adds nothing."""
    position = 0
    for value in whole:
        if position < len(part) and part[position] == value:
            position += 1
    return position == len(part)


def validate(manifest):
    """Reject any manifest that is not a complete, pinned, licensed pack record."""
    if not isinstance(manifest, dict) or manifest.get('schema') != SCHEMA:
        raise PackError('Unsupported benchmark pack schema')
    if set(manifest) - _MANIFEST_KEYS:
        raise PackError('Benchmark pack manifest has unknown fields')
    pack = manifest.get('pack')
    if not isinstance(pack, str) or len(pack) > 48 or not _PACK_ID.fullmatch(pack):
        raise PackError('Benchmark pack needs a lowercase identifier')
    if not _text(manifest.get('name'), 64):
        raise PackError('Benchmark pack needs a name')
    label = manifest.get('label')
    if not _text(label, 96) or not re.search(r'\b(?:sub)?set\b', label):
        raise PackError('Benchmark pack label must say it is a set or subset')
    if not isinstance(manifest.get('version'), str) or not _VERSION.fullmatch(manifest['version']):
        raise PackError('Benchmark pack needs a numbered version')
    if not isinstance(manifest.get('adapter'), str) or not _ADAPTER.fullmatch(manifest['adapter']):
        raise PackError('Benchmark pack needs a named adapter')

    upstream = manifest.get('upstream')
    if not isinstance(upstream, dict) or set(upstream) != {'url', 'revision'}:
        raise PackError('Benchmark pack needs an upstream URL and a pinned revision')
    revision = upstream['revision']
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        raise PackError('Benchmark pack needs a pinned revision (a full 40-character commit)')
    if not _https(upstream['url'], hosts=ALLOWED_HOSTS):
        raise PackError('Benchmark pack upstream URL must be HTTPS on a reviewed host')

    files = manifest.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise PackError('Benchmark pack needs file hashes')
    names = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {'name', 'url', 'sha256', 'size'}:
            raise PackError('Each benchmark pack file needs a name, URL, SHA-256 and size')
        if (not isinstance(entry['name'], str) or not _FILE_NAME.fullmatch(entry['name'])
                or entry['name'].lower() in names or entry['name'].endswith('.partial')
                or entry['name'] == 'receipt.json'):
            raise PackError('Benchmark pack file names must be plain and unique')
        names.add(entry['name'].lower())
        if not isinstance(entry['sha256'], str) or not _SHA256.fullmatch(entry['sha256']):
            raise PackError('Each benchmark pack file needs a SHA-256 hash')
        if type(entry['size']) is not int or not 1 <= entry['size'] <= MAX_FILE_BYTES:
            raise PackError('Each benchmark pack file needs its exact size')
        if not _https(entry['url'], hosts=ALLOWED_HOSTS):
            raise PackError('Each benchmark pack file URL must be HTTPS on a reviewed host')
        # The upstream revision pins provenance; size and SHA-256 pin the exact bytes even
        # when an authoritative source exposes its archive at a stable, non-versioned URL.

    licences = manifest.get('licences')
    if not isinstance(licences, list) or not 1 <= len(licences) <= 4:
        raise PackError('Benchmark pack needs a licence record')
    covered = []
    for entry in licences:
        if (not isinstance(entry, dict) or set(entry) != {'applies_to', 'id', 'url'}
                or entry['applies_to'] not in ('dataset', 'selection') or entry['applies_to'] in covered
                or not isinstance(entry['id'], str) or not _LICENCE_ID.fullmatch(entry['id'])
                or not _https(entry['url'])):
            raise PackError('Each licence record needs what it applies to, an identifier and the '
                            'HTTPS URL of the upstream licence file')
        covered.append(entry['applies_to'])
    if 'dataset' not in covered:
        raise PackError('Benchmark pack needs a licence record for the dataset')

    gated = manifest.get('gated')
    if type(gated) is not bool:
        raise PackError('Benchmark pack must say whether its source is gated')
    terms = manifest.get('terms_url')
    if gated and not _https(terms):
        raise PackError('A gated benchmark pack needs the HTTPS URL of the upstream terms')
    if not gated and terms is not None:
        raise PackError('Only a gated benchmark pack carries upstream terms')

    items = manifest.get('items')
    if (not isinstance(items, dict) or set(items) != {'version', 'ids'}
            or not isinstance(items['version'], str)
            or not re.fullmatch(r'[a-z0-9][a-z0-9._/-]{0,63}', items['version'])):
        raise PackError('Benchmark pack needs a versioned item-ID list')
    ids = items['ids']
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_ITEMS
            or any(not isinstance(value, str) or not _ITEM_ID.fullmatch(value) for value in ids)
            or len(set(ids)) != len(ids)):
        raise PackError('Benchmark pack item IDs must be unique plain identifiers')

    slices = manifest.get('slices')
    if not isinstance(slices, dict) or set(slices) != set(SIZES):
        raise PackError('Benchmark pack needs quick, standard and full lap slices')
    for size in SIZES:
        part = slices[size]
        if (not isinstance(part, list) or not part or any(not isinstance(value, str) for value in part)
                or len(set(part)) != len(part) or not _subsequence(part, ids)):
            raise PackError('Each lap slice must be an ordered part of the item-ID list')
    if slices['full'] != ids:
        raise PackError('The full lap slice must be the whole item-ID list')
    if not _subsequence(slices['quick'], slices['standard']):
        raise PackError('Lap slices must be nested: quick inside standard inside full')
    return manifest


def _decode(raw):
    def reject(_value):
        raise ValueError('Nonfinite JSON number')
    return json.loads(raw, object_pairs_hook=ability.object_pairs, parse_constant=reject)


def load_manifest(pack, *, root=None):
    """Load one shipped manifest by pack identifier."""
    root = DATA if root is None else Path(root)
    if not isinstance(pack, str) or len(pack) > 48 or not _PACK_ID.fullmatch(pack):
        raise PackError('Unknown benchmark pack')
    path = root / (pack + '.json')
    try:
        with path.open('rb') as stream:
            raw = stream.read(MANIFEST_LIMIT + 1)
    except OSError:
        raise PackError('Unknown benchmark pack') from None
    if len(raw) > MANIFEST_LIMIT:
        raise PackError('Benchmark pack manifest exceeds its size limit')
    try:
        manifest = _decode(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise PackError('Benchmark pack manifest is not valid JSON') from None
    validate(manifest)
    if manifest['pack'] != pack:
        raise PackError('Benchmark pack manifest name differs from its file')
    return manifest


def manifest_path(pack, *, root=None):
    return (DATA if root is None else Path(root)) / (pack + '.json')


def available(*, root=None):
    """Every shipped pack manifest, in name order. An invalid manifest is an error."""
    root = DATA if root is None else Path(root)
    if not root.is_dir():
        return []
    return [load_manifest(path.stem, root=root) for path in sorted(root.glob('*.json'))]


def suite_name(pack):
    return SUITE_PREFIX + pack


def is_pack_suite(suite):
    return isinstance(suite, str) and suite.startswith(SUITE_PREFIX)


def pack_of(suite):
    if not is_pack_suite(suite):
        raise PackError('Unknown benchmark pack')
    return suite[len(SUITE_PREFIX):]


def store_root(home):
    """Packs live with the owner's data, beside saved results. Never in the image."""
    return storage.safe_local(Path(home).absolute() / '.local/share/argos-live/benchmark-packs')


def pack_directory(manifest, home):
    return storage.safe_local(store_root(home) / manifest['pack'] / manifest['upstream']['revision'])


def _confirmation(manifest):
    """Exactly what the owner must send back after reading the licence record."""
    value = {'pack': manifest['pack'], 'revision': manifest['upstream']['revision'],
             'licences': [entry['id'] for entry in manifest['licences']], 'accept_licences': True}
    if manifest['gated']:
        value.update(terms_url=manifest['terms_url'], accept_terms=True)
    return value


def review(manifest):
    """The licence gate: everything shown before a download can start."""
    validate(manifest)
    return {'pack': manifest['pack'], 'name': manifest['name'], 'label': manifest['label'],
            'version': manifest['version'], 'upstream': dict(manifest['upstream']),
            'files': [{'name': entry['name'], 'url': entry['url'], 'size': entry['size'],
                       'sha256': entry['sha256']} for entry in manifest['files']],
            'download_bytes': sum(entry['size'] for entry in manifest['files']),
            'licences': [dict(entry) for entry in manifest['licences']],
            'gated': manifest['gated'], 'terms_url': manifest['terms_url'],
            'questions': len(manifest['items']['ids']), 'footnotes': list(FOOTNOTES),
            'notice': ('This downloads a public benchmark from its original source. '
                       'Nothing is uploaded. Scores from it are a subset and are not the official score.'),
            'confirmation_required': _confirmation(manifest)}


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()


_VERIFIED = {}


def verify_files(manifest, directory, *, cached=False):
    """Check every pinned file by size and SHA-256. A mismatch names the file.

    `cached=True` (status display only) trusts a hash already computed in this
    process for the same path, size and modification time.
    """
    directory = Path(directory)
    found = {}
    for entry in manifest['files']:
        path = directory / entry['name']
        try:
            info = path.lstat()
        except OSError:
            raise PackNotDownloaded(f'{manifest["label"]}: not downloaded') from None
        if path.is_symlink() or not path.is_file():
            raise PackRefused(f'{entry["name"]}: not a regular file; the pack is refused')
        if info.st_size != entry['size']:
            raise PackRefused(f'{entry["name"]}: size differs from the pinned file; the pack is refused')
        key = (str(path), info.st_size, info.st_mtime_ns)
        digest = _VERIFIED.get(key) if cached else None
        if digest is None:
            digest = _hash(path)
            if len(_VERIFIED) > 256:
                _VERIFIED.clear()
            _VERIFIED[key] = digest
        if digest != entry['sha256']:
            raise PackRefused(f'{entry["name"]}: SHA-256 does not match the pinned value; the pack is refused')
        found[entry['name']] = path
    return found


def _receipt(manifest, home):
    """The owner's saved confirmation for this exact pack revision and licence record."""
    path = pack_directory(manifest, home) / 'receipt.json'
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return None
    if (value.get('schema') != RECEIPT_SCHEMA or value.get('confirmation') != _confirmation(manifest)
            or not isinstance(value.get('confirmed_at'), str)):
        return None
    return value


def status(manifest, home):
    """Owner-facing state of one pack: 'not downloaded', 'downloaded' or 'refused'."""
    base = {'pack': manifest['pack'], 'suite': suite_name(manifest['pack']), 'name': manifest['name'],
            'label': manifest['label'], 'version': manifest['version'],
            'questions': len(manifest['items']['ids']),
            'slices': {size: len(manifest['slices'][size]) for size in SIZES},
            'download_bytes': sum(entry['size'] for entry in manifest['files']),
            'gated': manifest['gated'], 'terms_url': manifest['terms_url'],
            'upstream': dict(manifest['upstream']),
            'licences': [dict(entry) for entry in manifest['licences']],
            'footnotes': list(FOOTNOTES), 'state': 'not downloaded', 'reason': None}
    try:
        if _receipt(manifest, home) is None:
            return base
        verify_files(manifest, pack_directory(manifest, home), cached=True)
    except PackNotDownloaded:
        return base
    except PackRefused as error:
        return {**base, 'state': 'refused', 'reason': str(error)}
    except (OSError, ValueError):
        return base
    return {**base, 'state': 'downloaded'}


def overview(home, *, root=None):
    """All shipped packs with their state. Works offline; reads nothing remote."""
    return [status(manifest, home) for manifest in available(root=root)]


ADAPTERS = {}


def adapter(name):
    """Register `function(manifest, files) -> items` under a manifest adapter name."""
    if not isinstance(name, str) or not _ADAPTER.fullmatch(name):
        raise ValueError('Invalid adapter name')

    def register(function):
        ADAPTERS[name] = function
        return function
    return register


def _choice_item(ident, question, choices, expected):
    prompt = ('Choose the correct option. Reply with only A, B, C or D.\n\n' +
              question + '\n' + '\n'.join(f'{letter}. {choice}'
                                           for letter, choice in zip('ABCD', choices)))
    wrong = next(letter for letter in 'ABCD' if letter != expected)
    return {'id': ident, 'prompt': prompt, 'scorer': {'kind': 'choice', 'expected': expected},
            'reference': expected, 'wrong': wrong,
            'malformed': 'I cannot identify one of the four letters.'}


@adapter('mmlu-tar')
def _mmlu_tar(manifest, files):
    """Read only selected test rows from the official MMLU data archive."""
    wanted = {}
    for ident in manifest['items']['ids']:
        parts = ident.split('/')
        if len(parts) != 4 or parts[:2] != ['mmlu', 'test'] or not parts[3].isdigit():
            raise PackRefused('MMLU item list contains an invalid subject row ID')
        wanted.setdefault(parts[2], set()).add(int(parts[3]))
    rows = {}
    try:
        with tarfile.open(files['mmlu-data.tar'], mode='r:') as archive:
            for member in archive:
                prefix = 'data/test/'
                if (not member.isfile() or not member.name.startswith(prefix) or
                        not member.name.endswith('_test.csv')):
                    continue
                subject = member.name[len(prefix):-len('_test.csv')]
                indices = wanted.get(subject)
                if not indices:
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                with io.TextIOWrapper(stream, encoding='utf-8', newline='') as text:
                    for index, row in enumerate(csv.reader(text)):
                        if index not in indices:
                            continue
                        if (len(row) != 6 or not row[0].strip() or
                                any(not value.strip() for value in row[1:5]) or
                                row[5].strip() not in 'ABCD' or len(row[5].strip()) != 1):
                            raise PackRefused(f'MMLU subject {subject} row {index} is malformed')
                        ident = f'mmlu/test/{subject}/{index:04d}'
                        rows[ident] = _choice_item(ident, row[0].strip(),
                                                   [value.strip() for value in row[1:5]],
                                                   row[5].strip())
    except (tarfile.TarError, OSError, UnicodeError, csv.Error) as error:
        raise PackRefused(f'MMLU archive is not readable ({type(error).__name__})') from None
    return [rows[ident] for ident in manifest['items']['ids'] if ident in rows]


@adapter('gsm8k-jsonl')
def _gsm8k_jsonl(manifest, files):
    """Read the fixed GSM8K test rows, reducing each reference to its final number."""
    wanted = {}
    for ident in manifest['items']['ids']:
        prefix = 'gsm8k/test/'
        suffix = ident[len(prefix):] if ident.startswith(prefix) else ''
        if not suffix.isdigit() or len(suffix) != 4:
            raise PackRefused('GSM8K item list contains an invalid test row ID')
        wanted[int(suffix)] = ident
    rows = {}
    with files['gsm8k-test.jsonl'].open('rb') as stream:
        for index, line in enumerate(stream):
            if index not in wanted:
                continue
            value = _decode(line)
            question, answer = value.get('question'), value.get('answer')
            if not isinstance(question, str) or not isinstance(answer, str) or '####' not in answer:
                raise PackRefused(f'GSM8K test row {index} has no question or final answer')
            expected_text = answer.rsplit('####', 1)[1].strip()
            try:
                expected = Decimal(str(ability.numeric(expected_text)))
            except (ValueError, InvalidOperation):
                raise PackRefused(f'GSM8K test row {index} has no readable final number') from None
            expected_text = format(expected, 'f')
            wrong_text = format(expected + Decimal(1), 'f')
            ident = wanted[index]
            prompt = ('Solve the problem. Reply with only the final number, without units or explanation.\n\n' +
                      question)
            rows[ident] = {'id': ident, 'prompt': prompt,
                           'scorer': {'kind': 'numeric', 'expected': expected_text},
                           'reference': expected_text, 'wrong': wrong_text,
                           'malformed': 'No readable numeric answer.'}
    return [rows[ident] for ident in manifest['items']['ids'] if ident in rows]


def public_record(manifest):
    """What a saved run records about its pack. No question, no answer."""
    return {'pack': manifest['pack'], 'name': manifest['name'], 'label': manifest['label'],
            'version': manifest['version'], 'items_version': manifest['items']['version'],
            'revision': manifest['upstream']['revision'],
            'licences': [dict(entry) for entry in manifest['licences']],
            'subset': True, 'official_score': False, 'public': True}


def build_form(manifest, files, *, adapters=None):
    """Build the in-memory `argos-ability-suite/1` form through the named adapter."""
    validate(manifest)
    function = (ADAPTERS if adapters is None else adapters).get(manifest['adapter'])
    if function is None:
        raise PackError(f'No adapter named {manifest["adapter"]} is installed')
    try:
        items = function(manifest, files)
    except PackError:
        raise
    except (OSError, ValueError, KeyError, IndexError, TypeError, UnicodeError, EOFError) as error:
        raise PackRefused(f'{manifest["label"]}: the downloaded files are not in the expected '
                          f'upstream format ({type(error).__name__})') from None
    if not isinstance(items, list) or [item.get('id') if isinstance(item, dict) else None
                                       for item in items] != manifest['items']['ids']:
        raise PackRefused(f'{manifest["label"]}: the adapter did not produce the pinned item list')
    for item in items:
        if (set(item) != {'id', 'prompt', 'scorer', 'reference', 'wrong', 'malformed'}
                or not isinstance(item['prompt'], str) or not 1 <= len(item['prompt']) <= PROMPT_LIMIT
                or not isinstance(item['scorer'], dict) or item['scorer'].get('kind') not in ability.KINDS):
            raise PackRefused(f'{manifest["label"]}: item {item.get("id")} is not a scorable item')
        for field, outcome in (('reference', 'pass'), ('wrong', 'wrong_answer'), ('malformed', 'format_error')):
            if not isinstance(item[field], str) or ability.score(item, item[field])['outcome'] != outcome:
                raise PackRefused(f'{manifest["label"]}: item {item["id"]} does not match its scorer')
    dataset = next(entry for entry in manifest['licences'] if entry['applies_to'] == 'dataset')
    return {'schema': 'argos-ability-suite/1', 'suite': suite_name(manifest['pack']),
            'version': manifest['version'], 'license': dataset['id'], 'source': 'benchmark-pack',
            'omitted_categories': [], 'benchmark_pack': public_record(manifest), 'items': items}


def load_form(pack, home, *, root=None, adapters=None):
    """Verify a downloaded pack by hash and return its form. Refuses otherwise."""
    manifest = load_manifest(pack, root=root)
    if _receipt(manifest, home) is None:
        raise PackNotDownloaded(f'{manifest["label"]}: not downloaded')
    files = verify_files(manifest, pack_directory(manifest, home))
    return build_form(manifest, files, adapters=adapters)


def require_downloaded(suite, home, *, root=None):
    """Cheap pre-flight for a lap: say so before starting, not midway."""
    manifest = load_manifest(pack_of(suite), root=root)
    state = status(manifest, home)
    if state['state'] != 'downloaded':
        raise PackNotDownloaded(state['reason'] or f'{manifest["label"]}: not downloaded')
    return manifest


def _open_https(url):
    """The one network call: an owner-started GET of a pinned public file."""
    from urllib import request

    class HttpsOnly(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urlsplit(newurl).scheme != 'https':
                raise PackRefused('The download was redirected away from HTTPS')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = request.build_opener(HttpsOnly)
    return opener.open(request.Request(url, headers={'User-Agent': 'argos-live-pack-download'}),
                       timeout=60)


class Downloads:
    """Owner-started pack download: one at a time, durable state, verified by hash.

    State files reuse the pull-job primitives (atomic JSON, an OS-held worker
    lock, a separate control file for cancel). `opener(url)` returns a readable
    context manager; tests supply one, so no unit test touches the network.
    """

    def __init__(self, home, *, root=None, opener=None, free=None):
        self.home = storage.safe_local(Path(home).absolute())
        self.manifests = root
        self.opener = opener or _open_https
        self.free = free or (lambda path: shutil.disk_usage(path).free)
        self.state_root = storage.safe_local(self.home / '.local/state/argos-live/benchmark-pack-pulls')
        self.job_path = self.state_root / 'current.json'
        self.control_path = self.state_root / 'control.json'
        self.lock = threading.RLock()
        self.worker = None

    def _prepare(self):
        self.state_root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        Queue.initialize(self.state_root)

    def review(self, pack):
        return review(load_manifest(pack, root=self.manifests))

    def overview(self):
        return overview(self.home, root=self.manifests)

    def snapshot(self):
        try:
            job = read_json(self.job_path)
        except (OSError, ValueError):
            return {'available': True, 'state': 'idle'}
        if job.get('schema') != JOB_SCHEMA or job.get('state') not in JOB_STATES:
            return {'available': True, 'state': 'idle'}
        with self.lock:
            alive = self.worker is not None and self.worker.is_alive()
        if job['state'] in ('queued', 'downloading', 'verifying') and not alive:
            # Nothing resumes on its own after a restart; the owner starts it again.
            job = {**job, 'state': 'failed', 'error': 'The download was interrupted; start it again'}
        return {'available': True, **job}

    def _check(self, pack, confirmation):
        manifest = load_manifest(pack, root=self.manifests)
        if confirmation != _confirmation(manifest):
            if manifest['gated']:
                raise PackError(f'{manifest["label"]} is gated: read the upstream terms at '
                                f'{manifest["terms_url"]} and confirm them explicitly')
            raise PackError(f'{manifest["label"]}: read the licence record and confirm it explicitly')
        return manifest

    def start(self, pack, confirmation):
        """Begin a download in the background. Refused without the owner's confirmation."""
        manifest = self._check(pack, confirmation)
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                raise PackError('A benchmark pack download is already running')
            self._prepare()
            job = self._new_job(manifest)
            self.worker = threading.Thread(target=self._guarded, args=(manifest, confirmation, job),
                                           name='argos-benchmark-pack-download', daemon=False)
            self.worker.start()
            return {'available': True, **job}

    def run(self, pack, confirmation, *, progress=None):
        """Download in the calling thread (command line). Same gate, same checks."""
        manifest = self._check(pack, confirmation)
        self._prepare()
        return self._guarded(manifest, confirmation, self._new_job(manifest), progress=progress)

    def cancel(self):
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                raise PackError('No benchmark pack download is running')
        write_json(self.control_path, {'action': 'cancel'})
        return self.snapshot()

    def _new_job(self, manifest):
        total = sum(entry['size'] for entry in manifest['files'])
        job = {'schema': JOB_SCHEMA, 'id': secrets.token_hex(16), 'pack': manifest['pack'],
               'label': manifest['label'], 'revision': manifest['upstream']['revision'],
               'state': 'queued', 'error': None, 'created': stamp(), 'updated': stamp(),
               'progress': {'bytes_done': 0, 'bytes_total': total, 'file': None}}
        write_json(self.control_path, {'action': 'run'})
        write_json(self.job_path, job)
        return job

    def _cancelled(self):
        try:
            return read_json(self.control_path) != {'action': 'run'}
        except (OSError, ValueError):
            return True  # An unreadable owner control fails closed.

    def _guarded(self, manifest, confirmation, job, progress=None):
        def save(**changes):
            job.update(changes, updated=stamp())
            write_json(self.job_path, job)
            if progress:
                progress(json.loads(json.dumps(job)))
        try:
            with worker_lock(self.state_root):
                self._download(manifest, confirmation, job, save)
        except Cancelled:
            save(state='cancelled', error=None)
        except WorkerBusy:
            save(state='failed', error='Another benchmark pack download is running')
        except PackError as error:
            save(state='failed', error=str(error))
        except OSError as error:
            save(state='failed', error=f'The download did not finish ({type(error).__name__}); '
                                       'check the connection and free space, then start it again')
        return dict(job)

    def _download(self, manifest, confirmation, job, save):
        directory = pack_directory(manifest, self.home)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        missing = []
        for entry in manifest['files']:
            try:
                verify_files({**manifest, 'files': [entry]}, directory)
            except PackError:
                missing.append(entry)
        done = sum(entry['size'] for entry in manifest['files'] if entry not in missing)
        if self.free(directory) < sum(entry['size'] for entry in missing) + SPACE_MARGIN:
            raise PackError('Not enough free space for this benchmark pack')
        save(state='downloading', progress={**job['progress'], 'bytes_done': done})
        for entry in missing:
            if self._cancelled():
                raise Cancelled()
            partial = directory / (entry['name'] + '.partial')
            digest, received = hashlib.sha256(), 0
            try:
                with self.opener(entry['url']) as response, partial.open('wb') as stream:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > entry['size']:
                            raise PackRefused(f'{entry["name"]}: larger than the pinned file; '
                                              'the pack is refused')
                        digest.update(chunk)
                        stream.write(chunk)
                        if self._cancelled():
                            raise Cancelled()
                        save(progress={'bytes_done': done + received,
                                       'bytes_total': job['progress']['bytes_total'],
                                       'file': entry['name']})
                    stream.flush()
                    os.fsync(stream.fileno())
                if received != entry['size'] or digest.hexdigest() != entry['sha256']:
                    raise PackRefused(f'{entry["name"]}: SHA-256 does not match the pinned value; '
                                      'the pack is refused')
                os.replace(partial, directory / entry['name'])
            finally:
                partial.unlink(missing_ok=True)
            done += entry['size']
        save(state='verifying', progress={**job['progress'], 'bytes_done': done, 'file': None})
        verify_files(manifest, directory)
        write_json(directory / 'receipt.json',
                   {'schema': RECEIPT_SCHEMA, 'confirmation': confirmation, 'confirmed_at': stamp(),
                    'licences': [dict(entry) for entry in manifest['licences']],
                    'files': [{'name': entry['name'], 'sha256': entry['sha256']}
                              for entry in manifest['files']]})
        save(state='ready')


def _print_review(value, out):
    print(f'{value["label"]} (pack {value["pack"]}, version {value["version"]})', file=out)
    print(f'  Source: {value["upstream"]["url"]} at revision {value["upstream"]["revision"]}', file=out)
    for entry in value['files']:
        print(f'  File: {entry["name"]}, {entry["size"]:,} bytes, SHA-256 {entry["sha256"]}', file=out)
    for entry in value['licences']:
        print(f'  Licence ({entry["applies_to"]}): {entry["id"]}  {entry["url"]}', file=out)
    if value['gated']:
        print(f'  Gated source. Upstream terms: {value["terms_url"]}', file=out)
    print('  ' + value['notice'], file=out)


def main(argv=None, *, home=None, out=None, downloads=None):
    parser = argparse.ArgumentParser(
        description='Benchmark packs: public benchmark subsets downloaded by the owner.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='List packs and whether each is downloaded.')
    for name, text in (('review', 'Show the source, hashes and licence record of a pack.'),
                       ('download', 'Download a pack after confirming its licence record.')):
        sub = commands.add_parser(name, help=text)
        sub.add_argument('pack')
        if name == 'download':
            sub.add_argument('--accept-licences', action='store_true',
                             help='Confirm you have read the licence record shown by review.')
            sub.add_argument('--accept-terms', action='store_true',
                             help='Confirm you accept the upstream terms of a gated pack.')
    args = parser.parse_args(argv)
    out = out or sys.stdout
    downloads = downloads or Downloads(Path.home() if home is None else home)
    try:
        if args.command == 'status':
            for value in downloads.overview():
                print(f'{value["label"]}: {value["reason"] or value["state"]}', file=out)
            return 0
        value = downloads.review(args.pack)
        _print_review(value, out)
        if args.command == 'review':
            return 0
        if not args.accept_licences or (value['gated'] and not args.accept_terms):
            print('Not downloaded. Read the licence record above, then repeat with --accept-licences'
                  + (' and --accept-terms' if value['gated'] else '') + '.', file=out)
            return 2
        job = downloads.run(args.pack, value['confirmation_required'])
    except PackError as error:
        print(str(error), file=out)
        return 1
    print(f'{job["label"]}: {job["error"] or job["state"]}', file=out)
    return 0 if job['state'] == 'ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
