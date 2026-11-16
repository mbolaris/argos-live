#!/usr/bin/env python3
"""Save one real sidecar ability round and export only its public SIM5 ledger."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import ability, auto_setup, bench_openclaw, catalog, model_verify, owned_ollama
from argoslive.assistant_trial import OpenClawRunner
from argoslive.results import Store
from argoslive.shakedown import ledger as shakedown_ledger

SUITE = 'challenge'
MODEL_TAG = 'qwen3:4b-instruct-2507-q4_K_M'
TURN_TIMEOUT_SECONDS = 360


class ShakedownLedgerRunner(OpenClawRunner):
    """Allow a slower hosted CPU turn the same bound used by the sequence smoke."""

    def turn(self, text, timeout=TURN_TIMEOUT_SECONDS):
        return super().turn(text, timeout=timeout)


def run(cli, ollama, model_store, report):
    scratch = Path(os.environ.get('RUNNER_TEMP', '/missing')).resolve()
    model_store = model_store.resolve(strict=True)
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            scratch not in model_store.parents or os.geteuid() == 0):
        raise ValueError('The real SIM5 round requires an unprivileged disposable hosted fixture')
    entry = next((row for row in catalog.load()['models'] if row['tag'] == MODEL_TAG), None)
    if entry is None:
        raise ValueError('The SIM5 round requires the exact catalog-pinned model')
    identity = model_verify.verify(model_store, entry, sync=False, include_identity=True)

    with tempfile.TemporaryDirectory(prefix='argos-sim5-real-', dir=scratch) as temporary:
        home = Path(temporary)
        workspace = home / '.openclaw/workspace'
        workspace.mkdir(mode=0o700, parents=True)
        config_path = home / '.openclaw/openclaw.json'
        config_path.write_text(json.dumps(auto_setup.conversation_config(
            MODEL_TAG, workspace, plugin_root=ROOT / 'openclaw-plugin/argos-improve')), encoding='utf-8')
        config_path.chmod(0o600)
        lease_store = home / '.local/state/argos-live'
        lease_store.mkdir(mode=0o700, parents=True, exist_ok=True)
        runner = ShakedownLedgerRunner(home, executable=str(cli.resolve(strict=True)))
        runner.seed_workspace_defaults(('AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'BOOTSTRAP.md'),
                                       runner.bootstrap_templates())

        def progress(event):
            if event.get('phase') == 'scored':
                print(json.dumps({'completed': event.get('completed'), 'total': event.get('total'),
                                  'item_id': event.get('item_id')}, separators=(',', ':')),
                      file=sys.stderr, flush=True)

        store = Store(home / '.local/share/argos-live/results')
        with owned_ollama.owned(model_store, executable=str(ollama.resolve(strict=True)),
                                port=11434, context_tokens=32768, lease_store=lease_store):
            result = bench_openclaw.run(suite=SUITE, home=home, runner=runner, progress=progress)

        saved_path = store.root / (result['id'] + '.json')
        if not saved_path.is_file() or store.load(result['id']) != result:
            raise ValueError('The real sidecar result was not saved and verified in scratch')
        expected_version = 'argos-openclaw-ability/' + SUITE + '/' + ability.load(SUITE)['version']
        acceptance = {
            'completed': result.get('state') == 'completed',
            'coverage': result.get('coverage') == {'completed': 40, 'total': 40, 'complete': True},
            'suite_version': result.get('suite_version') == expected_version,
            'model': result.get('model') == 'ollama/' + MODEL_TAG,
            # Ollama reports the digest of its stored local manifest. The
            # verifier separately binds that manifest's artifacts to the
            # reviewed catalog revision, even when Ollama re-serializes it.
            'model_digest_matches_verified_manifest': (
                result.get('manifest_digest') == 'sha256:' + identity.get('local_manifest_sha256', '')),
        }
        if not all(acceptance.values()):
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({
                'schema': 'argos-sim5-hosted-acceptance-failure/1',
                'run_id': result.get('id'),
                'run_state': result.get('state'),
                'coverage': result.get('coverage'),
                'acceptance_checks': acceptance,
                'raw_answers_exported': False,
                'practice_only': True,
                'ci_commit': os.environ.get('GITHUB_SHA'),
            }, indent=2) + '\n', encoding='utf-8')
            raise ValueError('The real sidecar result failed acceptance: ' +
                             ', '.join(key for key, passed in acceptance.items() if not passed))

        fingerprint = shakedown_ledger.fingerprint_for(result)
        if fingerprint is None:
            raise ValueError('The real sidecar run has no verified model and instruction fingerprint')
        public_sim = shakedown_ledger.public_sim(shakedown_ledger.sim(result))
        public_ledger = shakedown_ledger.public_ledger(shakedown_ledger.ledger(store, fingerprint))
        receipt = {
            'schema': 'argos-sim5-hosted-acceptance/1',
            'run_id': result['id'],
            'suite_version': expected_version,
            'model': result['model'],
            'coverage': result['coverage'],
            'public_sim': public_sim,
            'public_ledger': public_ledger,
            'raw_answers_exported': False,
            'practice_only': True,
            'ci_commit': os.environ.get('GITHUB_SHA'),
        }
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--openclaw', type=Path, required=True)
    parser.add_argument('--ollama', type=Path, required=True)
    parser.add_argument('--model-store', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.openclaw, args.ollama, args.model_store, args.report)
    except BaseException as error:
        if not args.report.is_file():
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({
                'schema': 'argos-sim5-hosted-acceptance-failure/1',
                'failure_class': type(error).__name__,
                'raw_answers_exported': False,
                'practice_only': True,
            }, indent=2) + '\n', encoding='utf-8')
        raise
