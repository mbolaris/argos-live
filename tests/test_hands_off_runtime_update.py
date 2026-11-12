"""The Toronado runtime installer: apply, rollback and its refusals, on a throwaway tree."""
import hashlib, importlib.util, io, os, pathlib, sys, tarfile, tempfile, unittest

HERE = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'hands-off'
os.environ.setdefault('ARGOS_HANDS_OFF_DIR', tempfile.mkdtemp())
spec = importlib.util.spec_from_file_location('runtime_update', HERE / 'runtime_update.py')
ru = importlib.util.module_from_spec(spec); spec.loader.exec_module(ru)


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


if __name__ == '__main__':
    unittest.main()
