"""Owner-started, host-selected Proctor practice sessions through the managed gateway.

This service is cooperative enforcement for the same-UID Argos account. It is
deliberately practice-only until protected service identity and calibrated forms
are deployed. Agent tool calls cannot select the cartridge, form, exposure tier,
subject identity, policy, caller credential, or signing key.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys

from . import auto_setup, controller_bridge, owned_gateway, owned_ollama, proctor, session_mode, startup
from .proctor.engine import Caller
from .proctor.engine import digest
from .proctor.signing import Ed25519Signer, generate_key

PILOT_DEFINITION = Path(__file__).resolve().parent / 'data/proctor-practice-pilot.json'

PROCTOR_TOOL_NAMES = [
    'argos_proctor_start', 'argos_proctor_status', 'argos_proctor_item',
    'argos_proctor_answer', 'argos_proctor_continue', 'argos_proctor_submit',
    'argos_proctor_feedback',
]
POLICY = {'enforcement_level': 'declared', 'assistance_policy': 'closed_book'}
MESSAGE = ('Complete the host-selected Argos ability practice exam using only the '
           'argos_proctor_* tools. Start the exam, answer each active item, submit each '
           'module, continue when the host permits it, and request practice feedback '
           'after the final module. Do not use outside tools or infer whether an answer '
           'was correct before the host returns practice feedback. Then briefly identify '
           'the domains to practice next and stop without changing files or instructions.')


def _private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Proctor state path must not be a symbolic link')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'nt' and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
        raise ValueError('Proctor state directory must be private to the Argos account')
    return path


def _secret(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Proctor secret must not be a symbolic link')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if os.name != 'nt' and path.stat().st_mode & 0o077:
            raise ValueError('Proctor secret file permissions must be private')
        value = path.read_bytes()
        if len(value) != 32:
            raise ValueError('Proctor secret file is invalid')
        return value
    value = secrets.token_bytes(32)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    return value


def private_profile(home, model, *, plugin_root=None, owner_config_path=None):
    """Build a fresh tool-restricted config in the service-owned private directory."""
    home = Path(home)
    root = _private_directory(home / '.local/state/argos-live/proctor')
    profile = _private_directory(root / 'profiles' / hashlib.sha256(model.encode()).hexdigest()[:24])
    workspace = _private_directory(profile / 'workspace')
    config_path = profile / 'openclaw.json'
    if config_path.is_symlink():
        raise ValueError('Proctor config must not be a symbolic link')
    plugin_root = plugin_root or auto_setup.PLUGIN_ROOT
    config = auto_setup.conversation_config(model, workspace, plugin_root=plugin_root)
    config['gateway']['auth']['token'] = _secret(profile / 'gateway.token').hex()
    if owner_config_path is not None:
        owner_config = json.loads(Path(owner_config_path).read_text(encoding='utf-8'))
        source_provider = owner_config.get('models', {}).get('providers', {}).get('ollama', {})
        source_rows = source_provider.get('models', [])
        matches = [row for row in source_rows if isinstance(row, dict) and row.get('id') == model]
        primary = owner_config.get('agents', {}).get('defaults', {}).get('model', {})
        if (len(matches) != 1 or primary.get('primary') != 'ollama/' + model or
                source_provider.get('baseUrl') != 'http://127.0.0.1:11434'):
            raise ValueError('Owner-selected local model profile needs review before Proctor use')
        config['agents']['defaults']['model'] = json.loads(json.dumps(primary))
        config['models']['providers']['ollama']['models'] = [json.loads(json.dumps(matches[0]))]
    config['agents']['defaults']['heartbeat'] = {'every': '0m'}
    config['tools'] = {'profile': 'minimal', 'alsoAllow': PROCTOR_TOOL_NAMES,
                       'deny': ['group:runtime', 'group:web', 'exec', 'gateway', 'browser'],
                       'exec': {'host': 'gateway', 'security': 'full', 'ask': 'off'},
                       'elevated': {'enabled': False}, 'toolSearch': False}
    config['plugins']['allow'] = ['argos-improve']
    config['plugins']['slots'] = {'memory': 'none'}
    config['plugins']['entries']['argos-improve'] = {
        'enabled': True, 'config': {'hostAdmission': True},
        'hooks': {'allowConversationAccess': True}}
    config['skills'] = {'allowBundled': [], 'load': {'watch': False},
                        'workshop': {'autonomous': {'mode': 'off'}}}
    raw = (json.dumps(config, sort_keys=True, indent=2) + '\n').encode()
    if config_path.exists():
        prior = config_path.read_bytes()
        if prior != raw:
            raise ValueError('Existing Proctor profile differs; preserve it for owner review')
    else:
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return root, workspace, config_path, hashlib.sha256(raw).hexdigest()


def refuse_live_gateway(config_path):
    """Do not compete with an already-running everyday or unrelated gateway."""
    _origin, port = owned_gateway.settings(config_path)
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            raise ValueError('Stop the existing OpenClaw gateway before starting Proctor practice')
    except OSError:
        return


def refuse_live_backend():
    """Do not attach to an unrelated or already-running Ollama process."""
    try:
        with socket.create_connection(('127.0.0.1', 11434), timeout=0.2):
            raise ValueError('Stop the existing Ollama service before starting Proctor practice')
    except OSError:
        return


def make_session(home, cartridge_path, form_id, model, config_hash, *, openssl='openssl'):
    """Provision/reopen the service-owned practice database and host-only keys."""
    root = _private_directory(Path(home) / '.local/state/argos-live/proctor')
    cart = proctor.Cartridge(cartridge_path)
    if form_id not in cart.forms:
        raise ValueError('Unknown host-selected form in Proctor cartridge')
    if cart.manifest['calibration_status'] != 'uncalibrated':
        raise ValueError('Only explicitly uncalibrated cartridges are enabled by practice-only service')
    caller_id = 'argos-live-practice-agent'
    caller_token_path = root / 'caller.token'
    caller_token = _secret(caller_token_path).hex()
    token_secret = _secret(root / 'token.key')
    signing_path = root / 'transcript-ed25519.pem'
    if not signing_path.exists():
        generate_key(signing_path, executable=openssl)
    signer = Ed25519Signer(signing_path, executable=openssl)
    db = proctor.open_state(root / 'state.sqlite3')
    engine = proctor.Proctor(cart, db,
    callers={caller_id: Caller(token_hash=digest(caller_token),
                                   telemetry_trust='unavailable')},
        token_secret=token_secret, boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        signer=signer)
    subject = {'model': model, 'profile_sha256': config_hash,
               'cartridge_sha256': cart.digest}
    session = proctor.AgentSession(engine, caller_id=caller_id, caller_token=caller_token,
        form_id=form_id, tier='practice', subject=subject, policy=POLICY)
    return db, session, cart


def default_cartridge(home):
    """Compile the packaged pilot to a content-addressed private snapshot once."""
    root = _private_directory(Path(home) / '.local/state/argos-live/proctor')
    definition = json.loads(PILOT_DEFINITION.read_text(encoding='utf-8'))
    digest_value = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':'))
                                  .encode('utf-8')).hexdigest()
    directory = _private_directory(root / 'cartridges')
    destination = directory / (digest_value + '.sqlite3')
    if not destination.exists():
        try:
            proctor.compile_cartridge(definition, destination)
        except FileExistsError:
            pass
    cartridge = proctor.Cartridge(destination)
    if cartridge.manifest['calibration_status'] != 'uncalibrated':
        raise ValueError('Bundled Proctor pilot calibration status is invalid')
    return destination


def run_practice(home, cartridge_path=None, form_id='pilot-a', *, executable=None, openssl='openssl'):
    """Run one full owner-started practice exam under the exclusive host lease."""
    if sys.platform != 'linux':
        raise ValueError('Host-admitted Proctor practice currently requires Linux')
    if session_mode.guest():
        raise ValueError('Proctor practice cannot run in a reset-on-reboot guest session')
    home = Path(home).resolve(strict=True)
    state_path = home / '.config/argos-live/state.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    model = state.get('model')
    if not isinstance(model, str) or not model:
        raise ValueError('Argos local model selection is unavailable')
    if cartridge_path is None:
        cartridge_path = default_cartridge(home)
    target, selected_model = startup.source(home)
    if selected_model != model:
        raise ValueError('Argos model selection changed during Proctor setup')
    root, workspace, config_path, config_hash = private_profile(
        home, model, owner_config_path=home / '.openclaw/openclaw.json')
    refuse_live_gateway(config_path)
    refuse_live_backend()
    db, exam, cart = make_session(home, cartridge_path, form_id, model, config_hash, openssl=openssl)
    executable = executable or shutil.which('openclaw')
    if not executable:
        db.close()
        raise ValueError('Pinned OpenClaw executable is unavailable')
    try:
        with ExitStack() as stack:
            bridge, _ = stack.enter_context(controller_bridge.owned(
                home, session_key='agent:argos-proctor:practice', exam_session=exam))
            stack.enter_context(owned_ollama.owned(target, port=11434, context_tokens=32768,
                lease_store=home / '.local/state/argos-live'))
            stack.enter_context(owned_gateway.owned(home, executable=executable, config_path=config_path))
            bridge.launch(executable, MESSAGE, config_path=config_path, timeout=1800)
            result, _stderr = bridge.finish(timeout=1900)
        feedback = exam.practice_feedback()
        return {'status': 'completed', 'practice_only': True,
                'calibration_status': cart.manifest['calibration_status'],
                'cartridge_sha256': cart.digest, 'form_id': form_id,
                'transcript_id': exam.session_id.removeprefix('sess_'),
                'signing_key_id': exam.engine.signer.key_id,
                'result': feedback,
                'agent_summary': result.get('result', result).get('payloads', [])}
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    practice = commands.add_parser('practice', help='Run a host-selected, signed practice exam')
    practice.add_argument('--cartridge', type=Path,
                          help='Optional host-selected compiled cartridge (default: bundled four-item pilot)')
    practice.add_argument('--form', default='pilot-a')
    practice.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    home = Path.home()
    try:
        value = run_practice(home, args.cartridge, args.form)
        print(json.dumps(value, indent=2, ensure_ascii=False) if args.json else
              f"Practice complete: {value['result']['correct']}/{value['result']['total']}; "
              f"transcript {value['transcript_id']} (uncalibrated practice only).")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'Argos Proctor: {exc}\n')
