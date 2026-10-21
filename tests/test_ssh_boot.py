from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import ssh_boot


def policy(**overrides):
    values = dict(ssh_boot.REQUIRED, listenaddress='192.168.1.46:22',
                  allowusers='argos@192.168.1.31',
                  authorizedkeysfile='.ssh/authorized_keys .ssh/authorized_keys2')
    values.update(overrides)
    return '\n'.join(k + ' ' + v for k, v in values.items())


class SshPolicyTests(unittest.TestCase):
    def test_paired_lan_allowed(self):
        self.assertEqual(ssh_boot.effective_policy(policy()), [('argos', '192.168.1.31')])

    def test_rejects_all_interface_public_loopback_and_ipv6_listeners(self):
        for listener in ('0.0.0.0:22', '8.8.8.8:22', '127.0.0.1:22', '[::]:22'):
            with self.subTest(listener=listener), self.assertRaises(ValueError):
                ssh_boot.effective_policy(policy(listenaddress=listener))

    def test_rejects_missing_wildcard_public_or_root_allowlist(self):
        for allow in ('', '*', 'argos', 'root@192.168.1.31', 'argos@*',
                      'argos@192.168.1.*', 'argos@8.8.8.8', 'other@localhost'):
            with self.subTest(allow=allow), self.assertRaises(ValueError):
                ssh_boot.effective_policy(policy(allowusers=allow))

    def test_rejects_each_insecure_effective_setting(self):
        for name in ssh_boot.REQUIRED:
            with self.subTest(name=name), self.assertRaises(ValueError):
                ssh_boot.effective_policy(policy(**{name: 'unsafe'}))

    def test_additional_wildcard_listener_is_rejected(self):
        with self.assertRaises(ValueError):
            ssh_boot.effective_policy(policy() + '\nlistenaddress 0.0.0.0:22')

    def test_external_authorized_keys_not_accepted(self):
        with self.assertRaises(ValueError):
            ssh_boot.effective_policy(policy(authorizedkeysfile='/tmp/authorized_keys'))

    def test_requires_encrypted_live_persistence_for_identity(self):
        good = {'persistent': True, 'encrypted': True, 'live_persistence': True}
        with patch.object(ssh_boot.storage_view, 'backing', return_value=good):
            ssh_boot.require_encrypted(Path('/key'), [], {})
        for key in good:
            for value in (False, None):
                with self.subTest(key=key, value=value), patch.object(
                        ssh_boot.storage_view, 'backing', return_value=dict(good, **{key: value})):
                    with self.assertRaises(ValueError):
                        ssh_boot.require_encrypted(Path('/key'), [], {})

    @unittest.skipIf(os.name == 'nt', 'Unix ownership and permission enforcement')
    def test_missing_or_untrusted_pairing_file_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'key'
            with self.assertRaises(OSError):
                ssh_boot.trusted_file(file, {0})
            file.write_text('owner public key')
            file.chmod(0o600)
            ssh_boot.trusted_file(file, {file.stat().st_uid})
            with self.assertRaises(ValueError):
                ssh_boot.trusted_file(file, {-1})


class SshReadinessTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
                ('guest', False), ('trusted_file', None), ('require_encrypted', None),
                ('account_for', SimpleNamespace(pw_uid=1000, pw_dir='/home/argos')),
                ('command', policy())):
            target = ssh_boot.session_mode if name == 'guest' else ssh_boot
            patcher = patch.object(target, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch.object(ssh_boot.storage_view, 'topology', return_value=([], {}, 0))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(Path, 'stat', return_value=SimpleNamespace(st_mode=0o100600))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ready_checks_both_identity_and_authorized_keys_without_writing(self):
        ssh_boot.ready()
        self.assertEqual([c.args[0] for c in self.require_encrypted.call_args_list],
                         [ssh_boot.PAIRING, ssh_boot.HOST_KEY, Path('/home/argos/.ssh/authorized_keys')])
        commands = [c.args[0] for c in self.command.call_args_list]
        self.assertEqual(commands, [
            ['/usr/sbin/sshd', '-t'], ['/usr/sbin/sshd', '-T'],
            ['/usr/bin/ssh-keygen', '-l', '-f', str(Path('/home/argos/.ssh/authorized_keys'))],
            ['/usr/sbin/sshd', '-T', '-C', 'user=argos,addr=192.168.1.31,host=owner']])

    def test_guest_skips_before_accessing_keys(self):
        self.guest.return_value = True
        self.assertEqual(ssh_boot.main(), 1)
        self.trusted_file.assert_not_called()
        self.command.assert_not_called()

    def test_unpaired_image_skips_before_starting_sshd(self):
        self.trusted_file.side_effect = FileNotFoundError('no pairing')
        self.assertEqual(ssh_boot.main(), 1)
        self.command.assert_not_called()

    def test_does_not_regenerate_a_missing_host_key(self):
        self.trusted_file.side_effect = [None, FileNotFoundError('no host identity')]
        self.assertEqual(ssh_boot.main(), 1)
        self.command.assert_not_called()

    def test_ram_or_unknown_identity_storage_skips(self):
        self.require_encrypted.side_effect = ValueError('not encrypted')
        self.assertEqual(ssh_boot.main(), 1)
        self.command.assert_not_called()

    def test_match_override_rejected(self):
        self.command.side_effect = ['', policy(), 'owner key fingerprint', policy(passwordauthentication='yes')]
        self.assertEqual(ssh_boot.main(), 1)

    def test_invalid_existing_keys_are_not_replaced(self):
        self.command.side_effect = subprocess.CalledProcessError(1, ['/usr/sbin/sshd', '-t'])
        self.assertEqual(ssh_boot.main(), 1)
        self.assertEqual(self.command.call_count, 1)


@unittest.skipUnless(Path('/usr/sbin/sshd').is_file() and shutil.which('ssh-keygen'),
                     'Linux OpenSSH server and keygen required')
class RealOpenSshPolicyTests(unittest.TestCase):
    def test_installed_defaults_and_match_overrides_with_real_sshd(self):
        root = Path(__file__).resolve().parents[1]
        defaults = root / 'live/config/includes.chroot/etc/ssh/sshd_config.d/00-argos-defaults.conf'
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            key, config = folder / 'host_key', folder / 'sshd_config'
            subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
            base = defaults.read_text() + (f'\nHostKey {key}\nListenAddress 192.168.1.46\n'
                                          'AllowUsers argos@192.168.1.31\n')
            config.write_text(base)
            args = ['/usr/sbin/sshd', '-T', '-f', str(config), '-C',
                    'user=argos,addr=192.168.1.31,host=owner']
            output = ssh_boot.command(args)
            self.assertEqual(ssh_boot.effective_policy(output), [('argos', '192.168.1.31')])
            config.write_text(base + '\nMatch Address 192.168.1.31\n    PasswordAuthentication yes\n')
            with self.assertRaisesRegex(ValueError, 'passwordauthentication'):
                ssh_boot.effective_policy(ssh_boot.command(args))


if __name__ == '__main__':
    unittest.main()
