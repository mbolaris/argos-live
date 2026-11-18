"""The Toronado runtime installer: apply, rollback and its refusals, on a throwaway tree."""
import hashlib, importlib.util, io, os, pathlib, sys, tarfile, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'hands-off'
os.environ.setdefault('ARGOS_HANDS_OFF_DIR', tempfile.mkdtemp())
spec = importlib.util.spec_from_file_location('runtime_update', HERE / 'runtime_update.py')
ru = importlib.util.module_from_spec(spec); spec.loader.exec_module(ru)
sys.modules.setdefault('runtime_update', ru)  # apply_update imports it by name
spec = importlib.util.spec_from_file_location('apply_update', HERE / 'apply_update.py')
au = importlib.util.module_from_spec(spec); spec.loader.exec_module(au)


def bundle(files):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as t:
        for name, data in files.items():
            info = tarfile.TarInfo(ru.PREFIX + name); info.size = len(data); t.addfile(info, io.BytesIO(data))
    return out.getvalue()


def digest_of(files):
    return ru.digest({k: hashlib.sha256(v).hexdigest() for k, v in sorted(files.items())})


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.tmp.name)
        self.old, self.new = {'a.py': b'old\n', 'b.py': b'same\n'}, {'a.py': b'new\n', 'b.py': b'same\n', 'c.py': b'added\n'}
        tree = self.root / ru.TREE; tree.mkdir(parents=True)
        for k, v in self.old.items():
            (tree / k).write_bytes(v)
        self.data = bundle(self.new)
        self.sha = hashlib.sha256(self.data).hexdigest()
        staging = self.root / ru.STATE / 'staging'; staging.mkdir(parents=True)
        (staging / f'bundle-{self.sha[:16]}.tar').write_bytes(self.data)
        self.common = dict(bundle_sha256=self.sha, expect_before=digest_of(self.old), expect_after=digest_of(self.new))

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, action, stamp='t1', **over):
        return ru.run_installer(self.root, action=action, stamp=stamp, **{**self.common, **over})

    def test_apply_then_rollback_restores_the_old_tree(self):
        code, out, err = self.run_it('apply')
        self.assertEqual(code, 0, err); self.assertEqual(out['after'], self.common['expect_after'])
        self.assertEqual((self.root / ru.TREE / 'c.py').read_bytes(), b'added\n')
        code, out, err = self.run_it('rollback')
        self.assertEqual(code, 0, err); self.assertEqual(out['restored'], self.common['expect_before'])
        self.assertFalse((self.root / ru.TREE / 'c.py').exists())

    def test_refuses_wrong_hash_and_unexpected_installed_version(self):
        self.assertNotEqual(self.run_it('apply', bundle_sha256='0' * 64)[0], 0)
        (self.root / ru.TREE / 'a.py').write_bytes(b'tampered\n')
        self.assertNotEqual(self.run_it('apply')[0], 0)
        self.assertEqual((self.root / ru.TREE / 'a.py').read_bytes(), b'tampered\n')

    def test_refuses_a_path_that_escapes_the_tree(self):
        evil = bundle({'../../escape.py': b'x'}); sha = hashlib.sha256(evil).hexdigest()
        (self.root / ru.STATE / 'staging' / f'bundle-{sha[:16]}.tar').write_bytes(evil)
        self.assertNotEqual(self.run_it('apply', bundle_sha256=sha)[0], 0)
        self.assertEqual(list(self.root.rglob('escape.py')), [])


class HostPinTests(unittest.TestCase):
    """A bundle must name the OpenClaw version Toronado runs, and that is checked before any change."""

    def test_refusal_rule(self):
        self.assertIsNone(ru.host_pin_refusal('2026.11.3', 0, 'OpenClaw 2026.11.3 (a1b2c3)\n'))
        # November 18, 2026: bundle pinned 2026.10.8, Toronado ran 2026.11.3.
        reason = ru.host_pin_refusal('2026.10.8', 0, 'OpenClaw 2026.11.3 (a1b2c3)\n')
        self.assertIn('2026.10.8', reason); self.assertIn('2026.11.3', reason)
        self.assertIn('failed', ru.host_pin_refusal('2026.11.3', 127, ''))
        self.assertIn('no OpenClaw host pin', ru.host_pin_refusal(None, 0, 'OpenClaw 2026.11.3'))
        self.assertIn('no version', ru.host_pin_refusal('2026.11.3', 0, 'garbled'))

    def test_locate_finds_the_commit_for_an_installed_tree(self):
        head = ru.git('rev-list', '-1', 'HEAD', '--', 'runtime/argoslive')
        found, scanned = ru.locate(ru.digest(ru.manifest_of(ru.tree_tar(head))), per_ref=2)
        self.assertGreater(scanned, 0)
        self.assertIn(head, [f['commit'] for f in found])
        self.assertEqual(ru.locate('0' * 64, per_ref=2)[0], [])

    def test_head_runtime_pin_matches_image_pin(self):
        host, image = ru.pins_at('HEAD')
        self.assertTrue(host)
        self.assertEqual(host, image)


class PreflightTests(unittest.TestCase):
    RECEIPT = {'verified': True, 'file': 'unused.tar', 'bundle_sha256': 'a' * 64, 'expect_before': 'b' * 64,
               'expect_after': 'c' * 64, 'openclaw_host_version': '2026.11.3'}

    def remote(self, step='preflight', receipt=None, *, active=False, reported='OpenClaw 2026.11.3 (x)', current=None):
        """Load a step's remote script with Toronado stubbed out; return (namespace, calls, body)."""
        receipt = dict(self.RECEIPT if receipt is None else receipt)
        if step == 'apply':
            receipt['file'] = 'bundle-test.tar'; (ru.ROOT / receipt['file']).write_bytes(b'tar')
        script = au.script_for(step, receipt, 'test1')
        compile(script, step, 'exec')  # the whole remote script must at least parse
        body = au.STEPS[step]
        ns, calls = {}, []
        exec(compile(script[:-len(body)], 'setup', 'exec'), ns)  # ARGS, pin rule and helpers only
        ns['say'] = lambda **v: calls.append(('say', v))
        ns['campaign'] = lambda: calls.append(('campaign',)) or {'active': active, 'phase': 'idle'}
        ns['openclaw_version'] = lambda: calls.append(('openclaw',)) or (0, reported)
        ns['installer'] = lambda action, **e: calls.append(('installer', action)) or (
            0, {'current': current or receipt['expect_before'], 'files': 3}, '')
        return ns, calls, body

    def test_preflight_passes_when_pin_and_tree_match(self):
        ns, calls, _ = self.remote()
        self.assertIsNone(ns['preflight_checks']())
        self.assertIn(('installer', 'state'), calls)

    def test_preflight_refuses_version_mismatch_before_touching_the_tree(self):
        ns, calls, _ = self.remote(receipt={**self.RECEIPT, 'openclaw_host_version': '2026.10.8'})
        reason = ns['preflight_checks']()
        self.assertIn('2026.10.8', reason)
        self.assertNotIn(('installer', 'state'), calls)

    def test_preflight_refuses_active_evaluation_and_unexpected_tree(self):
        ns, calls, _ = self.remote(active=True)
        self.assertIn('evaluation is active', ns['preflight_checks']())
        self.assertNotIn(('openclaw',), calls)
        ns, calls, _ = self.remote(current='d' * 64)
        self.assertIn('expected pre-update version', ns['preflight_checks']())

    def test_apply_stops_before_staging_on_a_pin_mismatch(self):
        ns, calls, body = self.remote('apply', {**self.RECEIPT, 'openclaw_host_version': '2026.10.8'})
        ns['subprocess'] = None  # any staging, install or restart call would fail loudly
        with self.assertRaises(SystemExit) as stop:
            exec(compile(body, 'apply', 'exec'), ns)
        self.assertIn('refused before any change', str(stop.exception))
        self.assertEqual([c for c in calls if c[0] == 'installer'], [])

    def test_local_refusals_need_no_toronado_contact(self):
        with self.assertRaises(SystemExit):
            au.script_for('apply', {**self.RECEIPT, 'verified': False}, 't')
        old = {k: v for k, v in self.RECEIPT.items() if k != 'openclaw_host_version'}
        for step in ('preflight', 'apply'):
            with self.assertRaises(SystemExit):
                au.script_for(step, old, 't')
        # Read-only preflight may check a receipt whose CI checks have not finished yet.
        self.assertIn('preflight_checks()', au.script_for('preflight', {**self.RECEIPT, 'verified': False}, 't'))
        # Rollback must still work for receipts that predate the pin.
        self.assertIn("installer('rollback')", au.script_for('rollback', old, 't'))


if __name__ == '__main__':
    unittest.main()
