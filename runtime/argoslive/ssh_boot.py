"""Read-only boot gate for previously paired, encrypted-persistence SSH."""
import ipaddress
from pathlib import Path
import re
import stat
import subprocess

from . import session_mode, storage_view

PAIRING = Path('/etc/ssh/sshd_config.d/00-argos-lan.conf')
HOST_KEY = Path('/etc/ssh/ssh_host_ed25519_key')
PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in
                     ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
REQUIRED = {'pubkeyauthentication': 'yes', 'passwordauthentication': 'no',
            'kbdinteractiveauthentication': 'no', 'permitrootlogin': 'no',
            'disableforwarding': 'yes', 'authenticationmethods': 'publickey',
            'authorizedkeyscommand': 'none', 'trustedusercakeys': 'none',
            'strictmodes': 'yes'}


def command(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          timeout=10).stdout


def account_for(user):
    import pwd
    return pwd.getpwnam(user)


def private_address(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in net for net in PRIVATE_NETS):
        raise ValueError('SSH addresses must be on a trusted private IPv4 LAN')
    return address


def effective_policy(text):
    """Validate sshd's effective output, including each connection's Match rules."""
    settings = {}
    for line in text.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2:
            settings.setdefault(fields[0], []).append(fields[1])
    for key, value in REQUIRED.items():
        if settings.get(key) != [value]:
            raise ValueError('SSH policy does not enforce ' + key)
    if settings.get('authorizedkeysfile') not in (
            ['.ssh/authorized_keys'], ['.ssh/authorized_keys .ssh/authorized_keys2']):
        raise ValueError('SSH must use the paired local authorized_keys file')
    listeners = settings.get('listenaddress', [])
    if not listeners:
        raise ValueError('SSH needs an explicit private LAN listener')
    for listener in listeners:
        address, port = listener.rsplit(':', 1)
        private_address(address)
        if not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ValueError('Invalid SSH listener port')
    peers = []
    for item in ' '.join(settings.get('allowusers', [])).split():
        user, separator, address = item.partition('@')
        if not separator or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user) or user == 'root':
            raise ValueError('SSH requires explicit non-root users at owner LAN addresses')
        peers.append((user, str(private_address(address))))
    if not peers:
        raise ValueError('SSH has no paired owner allowlist')
    return peers


def trusted_file(path, owners):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('SSH pairing paths cannot be symbolic links')
    info = path.stat()
    if (not stat.S_ISREG(info.st_mode) or not info.st_size or
            info.st_uid not in owners or info.st_mode & 0o022):
        raise ValueError('SSH pairing files need trusted ownership and permissions')


def require_encrypted(path, mounts, blocks):
    evidence = storage_view.backing(path, mounts, blocks)
    if not (evidence['persistent'] is True and evidence['encrypted'] is True
            and evidence['live_persistence'] is True):
        raise ValueError('SSH pairing and host identity need unlocked encrypted live persistence')


def ready():
    """Never create keys, alter configuration, enable units, or accept a new pin."""
    if session_mode.guest():
        raise ValueError('SSH automatic startup is unavailable in guest mode')
    trusted_file(PAIRING, {0})
    trusted_file(HOST_KEY, {0})
    if HOST_KEY.stat().st_mode & 0o077:
        raise ValueError('SSH host private key permissions are too broad')
    mounts, blocks, _ = storage_view.topology()
    for path in (PAIRING, HOST_KEY):
        require_encrypted(path, mounts, blocks)
    # Test keys and configuration without starting a listener or generating keys.
    command(['/usr/sbin/sshd', '-t'])
    peers = effective_policy(command(['/usr/sbin/sshd', '-T']))
    for user, controller in peers:
        account = account_for(user)
        if account.pw_uid == 0:
            raise ValueError('SSH cannot use a root-equivalent account')
        authorized = Path(account.pw_dir) / '.ssh/authorized_keys'
        trusted_file(authorized, {0, account.pw_uid})
        require_encrypted(authorized, mounts, blocks)
        command(['/usr/bin/ssh-keygen', '-l', '-f', str(authorized)])
        scoped = effective_policy(command(['/usr/sbin/sshd', '-T', '-C',
                                           f'user={user},addr={controller},host=owner']))
        if set(scoped) != set(peers):
            raise ValueError('SSH Match rules change the paired owner allowlist')


def main():
    try:
        ready()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('Argos automatic SSH startup skipped: ' + str(exc))
        return 1  # ExecCondition: skip service; never fall back to unrestricted SSH.
    print('Argos paired LAN SSH policy and encrypted identity verified.')
    return 0
