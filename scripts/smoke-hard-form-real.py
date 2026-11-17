#!/usr/bin/env python3
"""Calibrate one EV2 form on the pinned disposable hosted OpenClaw model."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from argoslive import auto_setup, bench_openclaw, catalog, model_verify, owned_ollama
from argoslive.assistant_trial import OpenClawRunner
from argoslive.results import Store

MODEL_TAG = 'qwen3:4b-instruct-2507-q4_K_M'
SUITES = {'challenge-hard': 80, 'documents-long': 40}
LOWER_PERCENT, UPPER_PERCENT = 40, 70


class HostedRunner(OpenClawRunner):
    """Give long CPU turns a bounded six-minute allowance."""
    def turn(self, text, timeout=360):
        return super().turn(text, timeout=timeout)


def public_receipt(result, expected_total):
    """Keep only aggregate counts; never export answer text, prompt text or sealed item IDs."""
    if not isinstance(result, dict):
        raise ValueError('The hosted evaluation returned an invalid result')
    coverage = result.get('coverage')
    summary = result.get('summary')
    if (result.get('state') != 'completed' or coverage != {'completed': expected_total,
            'total': expected_total, 'complete': True} or not isinstance(summary, dict)
            or summary.get('total') != expected_total):
        raise ValueError('The hosted evaluation did not complete the full form')
    correct = summary.get('correct')
    format_errors = summary.get('format_errors')
    if (type(correct) is not int or not 0 <= correct <= expected_total
            or type(format_errors) is not int or not 0 <= format_errors <= expected_total):
        raise ValueError('The hosted evaluation has an invalid score')
    percent = round(correct * 100 / expected_total, 1)
    categories = summary.get('categories', {})
    partitions = summary.get('partitions', {})
    if not isinstance(categories, dict) or not isinstance(partitions, dict):
        raise ValueError('The hosted evaluation has invalid aggregate groups')
    def counts(grouped):
        result = {}
        for name, row in grouped.items():
            if (not isinstance(name, str) or not isinstance(row, dict)
                    or type(row.get('correct')) is not int or type(row.get('total')) is not int
                    or type(row.get('format_errors')) is not int
                    or not 0 <= row['correct'] <= row['total']
                    or not 0 <= row['format_errors'] <= row['total']):
                raise ValueError('The hosted evaluation has invalid aggregate counts')
            result[name] = {'correct': row['correct'], 'total': row['total'],
                            'format_errors': row['format_errors']}
        return result
    suite = result.get('suite', '').removeprefix('openclaw-')
    category_counts = counts(categories)
    partition_counts = counts(partitions)
    expected_categories = ({'numeric', 'choice', 'instruction', 'json', 'tool-call'}
                           if suite == 'challenge-hard'
                           else {'answer', 'quote', 'not_stated', 'summary'})
    half = expected_total // 2
    if (suite not in SUITES or set(category_counts) != expected_categories
            or set(partition_counts) != {'practice', 'heldout'}
            or sum(group['total'] for group in category_counts.values()) != expected_total
            or sum(group['correct'] for group in category_counts.values()) != correct
            or any(group['total'] != half for group in partition_counts.values())
            or sum(group['correct'] for group in partition_counts.values()) != correct):
        raise ValueError('The hosted evaluation has unexpected category or partition coverage')
    return {
        'schema': 'argos-ev2-calibration/1',
        'suite': suite,
        'suite_version': result.get('suite_version'),
        'model': result.get('model'),
        'coverage': coverage,
        'score': {'correct': correct, 'total': expected_total, 'percent': percent,
                  'format_errors': format_errors},
        'categories': category_counts,
        'partitions': partition_counts,
        'target_percent': [LOWER_PERCENT, UPPER_PERCENT],
        'in_target_band': LOWER_PERCENT <= percent <= UPPER_PERCENT,
        'raw_answers_exported': False,
        'prompts_exported': False,
    }


def run(cli, ollama, model_store, suite, report):
    if suite not in SUITES:
        raise ValueError('Choose challenge-hard or documents-long')
    scratch = Path(os.environ.get('RUNNER_TEMP', '/missing')).resolve()
    model_store = model_store.resolve(strict=True)
    if (sys.platform != 'linux' or os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            scratch not in model_store.parents or os.geteuid() == 0):
        raise ValueError('EV2 calibration requires an unprivileged disposable hosted fixture')
    entry = next((row for row in catalog.load()['models'] if row['tag'] == MODEL_TAG), None)
    if entry is None:
        raise ValueError('EV2 requires the exact catalog-pinned hosted model')
    identity = model_verify.verify(model_store, entry, sync=False, include_identity=True)
    total = SUITES[suite]

    with tempfile.TemporaryDirectory(prefix='argos-ev2-', dir=scratch) as temporary:
        home = Path(temporary)
        workspace = home / '.openclaw/workspace'
        workspace.mkdir(mode=0o700, parents=True)
        config_path = home / '.openclaw/openclaw.json'
        config_path.write_text(json.dumps(auto_setup.conversation_config(
            MODEL_TAG, workspace, plugin_root=ROOT / 'openclaw-plugin/argos-improve')), encoding='utf-8')
        config_path.chmod(0o600)
        lease_store = home / '.local/state/argos-live'
        lease_store.mkdir(mode=0o700, parents=True, exist_ok=True)
        runner = HostedRunner(home, executable=str(cli.resolve(strict=True)))
        runner.seed_workspace_defaults(('AGENTS.md', 'SOUL.md', 'IDENTITY.md', 'USER.md', 'BOOTSTRAP.md'),
                                       runner.bootstrap_templates())
        store = Store(home / '.local/share/argos-live/results')
        with owned_ollama.owned(model_store, executable=str(ollama.resolve(strict=True)),
                                port=11434, context_tokens=32768, lease_store=lease_store):
            result = bench_openclaw.run(suite=suite, home=home, runner=runner)
        saved = store.load(result['id'])
        if saved != result:
            raise ValueError('The complete hosted evaluation did not round-trip through the private result store')
        receipt = public_receipt(result, total)
        receipt['model_digest_matches_verified_manifest'] = (
            result.get('manifest_digest') == 'sha256:' + identity.get('local_manifest_sha256', ''))
        if not receipt['model_digest_matches_verified_manifest']:
            raise ValueError('The hosted result does not match the verified model manifest')
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        if not receipt['in_target_band']:
            raise ValueError(f'{suite} scored {receipt["score"]["percent"]}% outside the '
                             f'{LOWER_PERCENT}–{UPPER_PERCENT}% target band')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--openclaw', type=Path, required=True)
    parser.add_argument('--ollama', type=Path, required=True)
    parser.add_argument('--model-store', type=Path, required=True)
    parser.add_argument('--suite', choices=sorted(SUITES), required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.openclaw, args.ollama, args.model_store, args.suite, args.report)
    except BaseException as error:
        if not args.report.is_file():
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({
                'schema': 'argos-ev2-calibration-failure/1',
                'failure_class': type(error).__name__,
                'raw_answers_exported': False,
                'prompts_exported': False,
            }, indent=2) + '\n', encoding='utf-8')
        raise
