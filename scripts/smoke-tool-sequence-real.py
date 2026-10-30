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
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, auto_setup, bench_openclaw, catalog, model_verify, owned_ollama
from argoslive.assistant_trial import OpenClawRunner


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

        runner = OpenClawRunner(home, executable=str(cli.resolve(strict=True)))
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
        summary = result.get('summary', {})
        partitions = summary.get('partitions', {})
        expected_partitions = {'practice': 20, 'heldout': 20}
        if (result.get('state') != 'completed' or result.get('coverage') !=
                {'completed': 40, 'total': 40, 'complete': True} or
                result.get('model') != 'ollama/' + model_tag or
                result.get('suite_version') != 'argos-openclaw-ability/tool-sequence/' +
                    ability.load('tool-sequence')['version'] or
                result.get('settings', {}).get('execution_path') !=
                    'openclaw embedded; ephemeral state; tools denied; v2' or
                set(partitions) != set(expected_partitions) or
                any(partitions[name].get('total') != total
                    for name, total in expected_partitions.items())):
            raise ValueError('Tool-sequence result failed completion, identity, policy or partition checks')

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
            'practice_only': True,
            'calibration_status': 'uncalibrated',
            'internal_transfer_notice': (
                'Bundled held-out items are internal transfer checks, not independent validation.'),
            'coverage': result['coverage'],
            'summary': summary,
            'item_scores': [
                {key: item.get(key) for key in ('item_id', 'partition', 'category', 'score', 'outcome', 'checks')}
                for item in result['items']],
            'saved_result_sha256': hashlib.sha256(raw).hexdigest(),
            'ci_commit': os.environ.get('GITHUB_SHA'),
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.with_name('tool-sequence-real-run.json').write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
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
