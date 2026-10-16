"""Tool-free evaluation state, never an owner gateway session.

The fixed suites measure text answers (including proposed tool-call JSON), not
execution. A fresh HOME/state directory keeps interrupted evaluation work out of
the everyday gateway's durable queue. Deny policy is enforced by OpenClaw; it is
not a request that the model voluntarily refrain from using its normal tools.
"""
from contextlib import contextmanager, closing
import copy
import json
from pathlib import Path
import tempfile
import sqlite3
from urllib.parse import urlsplit

from . import storage

EXECUTION_PATH = 'openclaw embedded; ephemeral state; tools denied; v1'
WORKSPACE_FILES = ('AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'TOOLS.md')
FILE_LIMIT = 1024 * 1024


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
def isolated(home, workspace):
    """Copy bounded instruction/persona inputs, never credentials or session state."""
    home, workspace = Path(home), Path(workspace)
    original = json.loads(storage.safe_local(home / '.openclaw/openclaw.json').read_bytes())
    primary = original['agents']['defaults']['model']['primary']
    if not isinstance(primary, str) or not primary.startswith('ollama/'):
        raise ValueError('Evaluation requires a configured local Ollama model')
    tag = primary.removeprefix('ollama/')
    provider = original['models']['providers']['ollama']
    origin = urlsplit(provider['baseUrl'])
    if (origin.scheme != 'http' or origin.hostname != '127.0.0.1' or
            origin.port != 11434 or origin.username or origin.password or
            origin.query or origin.fragment or origin.path not in ('', '/')):
        raise ValueError('Evaluation requires the owned localhost model server')
    model = next((copy.deepcopy(row) for row in provider['models'] if row.get('id') == tag), None)
    if model is None:
        raise ValueError('Configured model metadata is unavailable')
    model = {key: model[key] for key in ('id', 'name', 'reasoning', 'input', 'cost', 'contextWindow', 'maxTokens')
             if key in model}
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
        config = {
            'agents': {'defaults': {'workspace': str(work), 'model': {'primary': primary},
                                    'heartbeat': {'every': '0m'}, 'skipBootstrap': True,
                                    'models': {primary: {'agentRuntime': {'id': 'openclaw'}}}}},
            'models': {'providers': {'ollama': {'baseUrl': 'http://127.0.0.1:11434',
                       'apiKey': 'ollama-local', 'api': 'ollama', 'models': [model]}}},
            # Tool Search stays off, as in the owner config: with every tool denied it
            # still offered a tool_search meta-tool, and a capable model looped on it
            # until the turn deadline (22 calls in 60 s) or answered about missing tools.
            'tools': {'deny': ['*'], 'toolSearch': False},
            # Ollama inference itself is a pinned bundled provider plugin in
            # OpenClaw 2026.10.4. Permit only it, never the campaign plugin/tools.
            'plugins': {'allow': ['ollama'], 'entries': {'ollama': {'enabled': True}},
                        'slots': {'memory': 'none'}},
            'skills': {'allowBundled': []},
        }
        # Carry only input-budget/model-generation settings, never owner routing,
        # plugins, fallbacks, external harnesses, auth profiles or shell env.
        for key in ('bootstrapMaxChars', 'bootstrapTotalMaxChars', 'contextTokens', 'thinkingDefault'):
            if key in original['agents']['defaults']:
                config['agents']['defaults'][key] = original['agents']['defaults'][key]
        path = root / '.openclaw/openclaw.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        path.chmod(0o600)
        yield root, path, work
