#!/usr/bin/env python3
"""Run the tool-sequence transfer suite against a catalog-verified model in scratch.

The benchmark asks for proposed call sequences only. The isolated evaluator
denies every tool, so this is not evidence that the model executed real tools.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL_SEQUENCE_TURN_TIMEOUT_SECONDS = 360
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, auto_setup, bench_openclaw, catalog, model_verify, owned_ollama
from argoslive.assistant_trial import OpenClawRunner


class ToolSequenceSmokeRunner(OpenClawRunner):
    """Give the isolated 40-item CPU smoke a bounded six-minute turn window."""

    def turn(self, text, timeout=TOOL_SEQUENCE_TURN_TIMEOUT_SECONDS):
        return super().turn(text, timeout=timeout)


def result_failures(result, model_tag, suite_version):
    """Return acceptance mismatches without copying model output into logs."""
    summary = result.get('summary', {})
    partitions = summary.get('partitions', {})
    expected_partitions = {'practice': 20, 'heldout': 20}
    failures = []
    if result.get('state') != 'completed':
        failures.append('state')
    if result.get('coverage') != {'completed': 40, 'total': 40, 'complete': True}:
        failures.append('coverage')
    if result.get('model') != 'ollama/' + model_tag:
        failures.append('model')
    if result.get('suite_version') != suite_version:
        failures.append('suite_version')
    if result.get('settings', {}).get('execution_path') != \
            'openclaw embedded; ephemeral state; tools denied; v2':
        failures.append('execution_policy')
    if set(partitions) != set(expected_partitions):
        failures.append('partition_names')
    elif any(partitions[name].get('total') != total
             for name, total in expected_partitions.items()):
        failures.append('partition_totals')
    return failures


def assistant_failure_signature(home):
    """Classify the private OpenClaw stderr log without exporting its contents."""
    path = Path(home) / '.local/state/argos-live/trial-turn-failure.log'
    try:
        text = path.read_bytes()[-65536:].decode('utf-8', errors='replace').lower()
    except OSError:
        return None
    categories = (
        ('model_unavailable', ('model not found', 'model does not exist', 'unknown model')),
        ('local_model_server_unreachable', ('connection refused', 'failed to connect', 'could not connect')),
        ('provider_authentication', ('unauthorized', 'authentication failed', 'invalid api key')),
        ('tool_policy_rejection', ('tool is not allowed', 'tool not allowed', 'tool use is disabled')),
        ('configuration_rejected', ('invalid config', 'configuration error', 'config validation')),
        ('upstream_timeout', ('timed out', 'timeout', 'deadline exceeded')),
    )
    for label, markers in categories:
        if any(marker in text for marker in markers):
            return label
    return 'unclassified_cli_error' if text else None


def safe_result_diagnostic(result, failures, failure_signature=None):
    """Keep bounded, non-sensitive run facts; omit prompts and model outputs."""
    allowed_failure_codes = {
        'cancelled', 'turn-timeout', 'assistant-error', 'empty-reply',
        'invalid-reply', 'session-mismatch', 'model-mismatch',
        'workspace-changed-during-run', 'configuration-changed-during-run',
        'benchmark-changed-during-run', 'instruction-changed-during-run',
    }
    failure_code = result.get('failure_code')
    return {
        'schema': 'argos-tool-sequence-model-smoke-run/1',
        'run_id': result.get('id'),
        'state': result.get('state'),
        'failure_code': failure_code if failure_code in allowed_failure_codes else None,
        'assistant_failure_signature': failure_signature,
        'turn_timeout_seconds': TOOL_SEQUENCE_TURN_TIMEOUT_SECONDS,
        'model': result.get('model'),
        'suite_version': result.get('suite_version'),
        'coverage': result.get('coverage'),
        'summary': result.get('summary', {}),
        'execution_path': result.get('settings', {}).get('execution_path'),
        'item_scores': [
            {key: item.get(key) for key in
             ('item_id', 'partition', 'category', 'score', 'outcome', 'checks')}
            for item in result.get('items', []) if isinstance(item, dict)],
        'acceptance_failures': failures,
    }


def run(cli, ollama, model_store, model_tag, report):
    scratch = Path(os.environ.get('RUNNER_TEMP', '/missing')).resolve()
    model_store = model_store.resolve(strict=True)
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            scratch not in model_store.parents or os.geteuid() == 0):
        raise ValueError('Tool-sequence model run requires an unprivileged disposable hosted fixture')

    entry = next((row for row in catalog.load()['models'] if row['tag'] == model_tag), None)
    if entry is None or 'tools' not in entry['capabilities']:
        raise ValueError('Tool-sequence model run requires an exact catalog-pinned tool-capable model')
    identity = model_verify.verify(model_store, entry, sync=False, include_identity=True)

    with tempfile.TemporaryDirectory(prefix='argos-tool-sequence-', dir=scratch) as temporary:
        home = Path(temporary)
        workspace = home / '.openclaw/workspace'
        workspace.mkdir(mode=0o700, parents=True)
        config = auto_setup.conversation_config(model_tag, workspace,
            plugin_root=ROOT / 'openclaw-plugin/argos-improve')
        config_path = home / '.openclaw/openclaw.json'
        config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config), encoding='utf-8')
        config_path.chmod(0o600)
        lease_store = home / '.local/state/argos-live'
        lease_store.mkdir(mode=0o700, parents=True, exist_ok=True)

        runner = ToolSequenceSmokeRunner(home, executable=str(cli.resolve(strict=True)))
        runner.seed_workspace_defaults(
            ('AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'BOOTSTRAP.md'),
            runner.bootstrap_templates())

        def progress(event):
            if event.get('phase') == 'scored':
                print(json.dumps({'completed': event.get('completed'),
                                  'total': event.get('total'),
                                  'item_id': event.get('item_id')}, separators=(',', ':')),
                      file=sys.stderr, flush=True)

        with owned_ollama.owned(model_store, executable=str(ollama.resolve(strict=True)),
                port=11434, context_tokens=32768, lease_store=lease_store):
            result = bench_openclaw.run(suite='tool-sequence', home=home,
                                        runner=runner, progress=progress)

        saved = home / '.local/share/argos-live/results' / (result['id'] + '.json')
        if not saved.is_file() or json.loads(saved.read_text(encoding='utf-8')) != result:
            raise ValueError('Tool-sequence result was not saved and verified in scratch')
        raw = saved.read_bytes()
        suite_version = 'argos-openclaw-ability/tool-sequence/' + ability.load('tool-sequence')['version']
        failures = result_failures(result, model_tag, suite_version)
        run_diagnostic = safe_result_diagnostic(
            result, failures, assistant_failure_signature(home))
        report.with_name('tool-sequence-real-run.json').write_text(
            json.dumps(run_diagnostic, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        if failures:
            raise ValueError('Tool-sequence result failed acceptance: ' + ', '.join(failures))

        receipt = {
            'schema': 'argos-tool-sequence-model-smoke/1',
            'run_id': result['id'],
            'model': result['model'],
            'model_identity_sha256': identity['sha256'],
            'model_catalog_manifest_digest': identity['catalog_manifest_digest'],
            'verified_model_bytes': identity['verified_bytes'],
            'suite_version': result['suite_version'],
            'suite_sha256': result['settings']['suite_sha256'],
            'execution_path': result['settings']['execution_path'],
            'tools_executed': False,
            'turn_timeout_seconds': TOOL_SEQUENCE_TURN_TIMEOUT_SECONDS,
            'practice_only': True,
            'calibration_status': 'uncalibrated',
            'internal_transfer_notice': (
                'Bundled held-out items are internal transfer checks, not independent validation.'),
            'coverage': result['coverage'],
            'summary': result.get('summary', {}),
            'item_scores': [
                {key: item.get(key) for key in ('item_id', 'partition', 'category', 'score', 'outcome', 'checks')}
                for item in result['items']],
            'saved_result_sha256': hashlib.sha256(raw).hexdigest(),
            'ci_commit': os.environ.get('GITHUB_SHA'),
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('openclaw', 'ollama', 'model-store', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--model-tag', required=True)
    args = parser.parse_args()
    try:
        run(args.openclaw, args.ollama, args.model_store, args.model_tag, args.report)
    except BaseException as error:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            'schema': 'argos-tool-sequence-model-smoke-failure/1',
            'failure_class': type(error).__name__,
            'practice_only': True,
            'calibration_status': 'uncalibrated',
            'tools_executed': False,
        }, indent=2) + '\n', encoding='utf-8')
        raise
