"""Tool-free evaluation state, never an owner gateway session.

The fixed suites measure text answers (including proposed tool-call JSON), not
execution. A fresh HOME/state directory keeps interrupted evaluation work out of
the everyday gateway's durable queue. Deny policy is enforced by OpenClaw; it is
not a request that the model voluntarily refrain from using its normal tools.
"""
from contextlib import contextmanager, closing
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import sqlite3
from urllib.parse import urlsplit

from . import storage

EXECUTION_PATH = 'openclaw embedded; ephemeral state; tools denied; v2'
WORKSPACE_FILES = ('AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'TOOLS.md')
FILE_LIMIT = 1024 * 1024
TRIAL_CONTEXT_TOKENS = 32768
DEFAULT_SETTINGS = ('bootstrapMaxChars', 'bootstrapTotalMaxChars', 'contextTokens', 'thinkingDefault')
# Pinned native Ollama request/runtime controls. Never transport, routing,
# headers, credentials, plugins, external harnesses or tool policy.
NUMERIC_PARAMS = frozenset(('temperature', 'topP', 'maxTokens', 'seed', 'frequencyPenalty', 'presencePenalty',
    'num_ctx', 'num_keep', 'num_predict', 'top_k', 'top_p', 'min_p', 'typical_p', 'repeat_last_n',
    'repeat_penalty', 'presence_penalty', 'frequency_penalty', 'num_batch', 'num_gpu', 'main_gpu', 'num_thread'))
BOOL_PARAMS = frozenset(('use_mmap', 'truncate', 'shift', 'streaming'))
THINK_LEVELS = frozenset(('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'adaptive', 'max', 'ultra', 'disabled', 'none'))


def parameters(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('Evaluation generation parameters must be an object')
    for key, setting in value.items():
        valid = False
        if key in NUMERIC_PARAMS:
            valid = type(setting) in (int, float) and math.isfinite(setting)
        elif key in BOOL_PARAMS:
            valid = type(setting) is bool
        elif key in ('think', 'thinking'):
            valid = type(setting) is bool or isinstance(setting, str) and setting in THINK_LEVELS
        elif key == 'stop':
            valid = isinstance(setting, str) or (isinstance(setting, list) and all(isinstance(x, str) for x in setting))
        elif key == 'format':
            valid = setting == 'json' or isinstance(setting, dict)
        elif key == 'keep_alive':
            # Kept as configuration evidence; a native request probe must still
            # establish which options the pinned provider actually exercised.
            valid = type(setting) in (int, float) and math.isfinite(setting) or isinstance(setting, str)
        if not valid:
            raise ValueError('Unsupported or invalid evaluation generation parameter')
    if len(json.dumps(value, allow_nan=False).encode()) > 65536:
        raise ValueError('Evaluation generation parameters exceed the limit')
    return copy.deepcopy(value)


def configuration(home, *, model_override=None):
    """Build the same bounded model configuration for copying and provenance."""
    original = json.loads(storage.safe_local(Path(home) / '.openclaw/openclaw.json').read_bytes())
    return configuration_from(original, model_override=model_override)


def catalog_model(tag):
    """Return reviewed metadata for one exact local model tag."""
    from . import catalog
    if not isinstance(tag, str) or not catalog.TAG.fullmatch(tag) or '/' in tag:
        raise ValueError('Evaluation model must be an exact reviewed local tag')
    data = catalog.load()
    row = next((item for item in data['models'] if item.get('tag') == tag), None)
    if row is None:
        raise ValueError('Evaluation model is not in the reviewed Argos catalog')
    return copy.deepcopy(row)


def _trial_parameters(value):
    result = parameters(value)
    result.pop('thinking', None)
    result.update(temperature=0, think=False, num_ctx=TRIAL_CONTEXT_TOKENS)
    return result


def configuration_from(original, *, model_override=None):
    """Pure projection, also used to verify a host's immutable config snapshot."""
    defaults = original['agents']['defaults']
    roster = original['agents']
    main = (roster['entries'].get('main', {}) if 'entries' in roster else
            next((row for row in roster.get('list', []) if row.get('id') == 'main'), {}))
    selected = main.get('model', defaults['model'])
    primary = selected if isinstance(selected, str) else selected['primary']
    if not isinstance(primary, str) or not primary.startswith('ollama/'):
        raise ValueError('Evaluation requires a configured local Ollama model')
    source_tag = primary.removeprefix('ollama/')
    provider = original['models']['providers']['ollama']
    origin = urlsplit(provider['baseUrl'])
    if (origin.scheme != 'http' or origin.hostname != '127.0.0.1' or
            origin.port != 11434 or origin.username or origin.password or
            origin.query or origin.fragment or origin.path not in ('', '/')):
        raise ValueError('Evaluation requires the owned localhost model server')
    source_row = next((row for row in provider['models'] if row.get('id') == source_tag), None)
    if source_row is None:
        raise ValueError('Configured model metadata is unavailable')
    tag = source_tag if model_override is None else model_override
    primary = 'ollama/' + tag
    selected_row = next((row for row in provider['models'] if row.get('id') == tag), None)
    if model_override is not None:
        entry = catalog_model(model_override)
        selected_row = copy.deepcopy(selected_row or source_row)
        selected_row.update(id=tag, name=tag,
                            reasoning='thinking' in entry['capabilities'],
                            input=['text', 'image'] if 'vision' in entry['capabilities'] else ['text'],
                            contextWindow=TRIAL_CONTEXT_TOKENS,
                            contextTokens=TRIAL_CONTEXT_TOKENS)
        selected_row['params'] = _trial_parameters(source_row.get('params'))
        selected_row['maxTokens'] = selected_row.get('maxTokens', source_row.get('maxTokens', 4096))
        selected_row['cost'] = copy.deepcopy(selected_row.get('cost', source_row.get('cost',
            {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0})))
    elif selected_row is None:
        raise ValueError('Configured model metadata is unavailable')
    model = {key: copy.deepcopy(selected_row[key]) for key in
             ('id', 'name', 'reasoning', 'input', 'cost', 'contextWindow', 'contextTokens', 'maxTokens')
             if key in selected_row}
    model['params'] = (parameters(selected_row.get('params')) if model_override is None else
                       _trial_parameters(source_row.get('params')))
    copied = {key: copy.deepcopy(defaults[key]) for key in DEFAULT_SETTINGS if key in defaults}
    defaults_params = parameters(defaults.get('params'))
    model_params = parameters(defaults.get('models', {}).get('ollama/' + source_tag, {}).get('params'))
    agent_params = parameters(main.get('params'))
    agent_model_params = parameters(main.get('models', {}).get('ollama/' + source_tag, {}).get('params'))
    provider_model_params = parameters(source_row.get('params'))
    if model_override is not None:
        copied['thinkingDefault'] = 'off'
        copied['contextTokens'] = TRIAL_CONTEXT_TOKENS
        defaults_params = _trial_parameters(defaults_params)
        model_params = _trial_parameters(model_params)
        agent_params = _trial_parameters(agent_params)
        agent_model_params = _trial_parameters(agent_model_params)
        provider_model_params = _trial_parameters(provider_model_params)
    copied.update(model={'primary': primary}, heartbeat={'every': '0m'}, skipBootstrap=True,
                  params=defaults_params,
                  models={primary: {'agentRuntime': {'id': 'openclaw'}, 'params': model_params}})
    agent = {'params': agent_params, 'models': {primary: {'params': agent_model_params}}}
    selected_row['params'] = provider_model_params
    local = {'baseUrl': 'http://127.0.0.1:11434', 'apiKey': 'ollama-local', 'api': 'ollama', 'models': [model]}
    if 'maxTokens' in provider:
        local['maxTokens'] = provider['maxTokens']
    return {'agents': {'defaults': copied, 'entries': {'main': agent}}, 'models': {'providers': {'ollama': local}},
            'tools': {'deny': ['*'], 'toolSearch': False},
            'plugins': {'allow': ['ollama'], 'entries': {'ollama': {'enabled': True}}, 'slots': {'memory': 'none'}},
            'skills': {'allowBundled': []}}


def configuration_receipt(home, *, model_override=None):
    return receipt_from(configuration(home, model_override=model_override))


def receipt_from(config):
    defaults = config['agents']['defaults']
    primary = defaults['model']['primary']
    agent = config['agents']['entries']['main']
    provider = config['models']['providers']['ollama']
    model = provider['models'][0]
    generation = {'defaults': {key: defaults[key] for key in DEFAULT_SETTINGS if key in defaults},
                  'default_params': defaults['params'], 'model_params': defaults['models'][primary]['params'],
                  'agent_params': agent['params'], 'agent_model_params': agent['models'][primary]['params'],
                  'provider_model_params': model['params']}
    if 'maxTokens' in provider:
        generation['provider_maxTokens'] = provider['maxTokens']
    generation = copy.deepcopy(generation)
    # Stop text or JSON schemas may contain private input. Retain a digest,
    # never publish their content in an otherwise safe configuration receipt.
    for scope in generation.values():
        if isinstance(scope, dict):
            for key in ('stop', 'format'):
                if key in scope:
                    scope[key] = {'sha256': hashlib.sha256(json.dumps(scope[key], sort_keys=True).encode()).hexdigest()}
    return {'sha256': hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest(),
            'model': {'primary': primary, 'metadata': {key: value for key, value in model.items()
                                                      if key not in ('id', 'name', 'cost', 'params')}},
            'configured_generation': generation}


def workspace_context_receipt(workspace):
    """Hash presence and bytes of copied persona inputs other than AGENTS.md."""
    workspace = Path(workspace)
    entries = []
    for name in WORKSPACE_FILES:
        if name == 'AGENTS.md':
            continue
        path = storage.safe_local(workspace / name)
        if not path.exists() and not path.is_symlink():
            entries.append({'name': name, 'present': False})
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size > FILE_LIMIT:
            raise ValueError('Evaluation workspace input is not a bounded regular file')
        raw = path.read_bytes()
        if len(raw) > FILE_LIMIT:
            raise ValueError('Evaluation workspace input exceeds the limit')
        entries.append({'name': name, 'present': True, 'sha256': hashlib.sha256(raw).hexdigest()})
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def require_no_legacy_trials(home):
    """Refuse restart over pending old gateway evaluations; never rewrite evidence."""
    for candidate in (Path(home) / '.openclaw/agents').glob('*/agent/openclaw-agent.sqlite'):
        path = storage.safe_local(candidate)
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as database:
                pending = database.execute(
                    "SELECT 1 FROM session_nodes WHERE session_key LIKE 'agent:%:argos-trial-%' "
                    "AND (status IS NULL OR status NOT IN ('done','completed','failed','cancelled','aborted')) LIMIT 1"
                ).fetchone()
        except sqlite3.Error:
            raise ValueError('Evaluation session recovery requires owner review; gateway was not started') from None
        if pending:
            raise ValueError('A legacy evaluation is pending; review recovery before starting the gateway')


@contextmanager
def isolated(home, workspace, *, model_override=None):
    """Copy bounded instruction/persona inputs, never credentials or session state."""
    home, workspace = Path(home), Path(workspace)
    config = configuration(home, model_override=model_override)
    with tempfile.TemporaryDirectory(prefix='argos-evaluation-') as temporary:
        root = Path(temporary)
        work = root / '.openclaw/workspace'
        work.mkdir(parents=True, mode=0o700)
        for name in WORKSPACE_FILES:
            source = workspace / name
            if not source.exists() and not source.is_symlink():
                continue
            source = storage.safe_local(source)
            if not source.is_file() or source.stat().st_size > FILE_LIMIT:
                raise ValueError('Evaluation workspace input is not a bounded regular file')
            raw = source.read_bytes()
            if len(raw) > FILE_LIMIT:
                raise ValueError('Evaluation workspace input exceeds the limit')
            (work / name).write_bytes(raw)
        config['agents']['defaults']['workspace'] = str(work)
        path = root / '.openclaw/openclaw.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        path.chmod(0o600)
        yield root, path, work
