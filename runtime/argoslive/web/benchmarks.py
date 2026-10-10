"""Read-only, bounded projections of private benchmark results."""
from itertools import islice
from pathlib import Path

from argoslive.results import Store, compare, export_csv, identifier


class View:
    def __init__(self, store=None):
        self.store = store or Store()

    def listing(self):
        rows, invalid = [], 0
        if not self.store.root.exists():
            return {'runs': [], 'invalid_count': 0, 'truncated': False}
        files = list(islice(self.store.root.glob('*.json'), 1025))
        truncated = len(files) > 1024
        files = files[:1024]
        def modified(path):
            try:
                return path.lstat().st_mtime
            except OSError:
                return 0
        files.sort(key=modified, reverse=True)
        truncated = truncated or len(files) > 128
        for path in files[:128]:
            try:
                run = self.store.load(path.stem)
                row = {key: run.get(key) for key in
                       ('id', 'created', 'kind', 'suite_version', 'model', 'manifest_digest', 'state', 'coverage')}
                if run['kind'] == 'ability':
                    row['summary'] = run['summary']
                    for key in ('qualification', 'document_context'):
                        if isinstance(run.get(key), dict):
                            row[key] = run[key]
                else:
                    from argoslive.bench_speed import numeric, summary
                    row['summary'] = [{'size': prompt['size'], 'skipped': prompt['skipped'],
                        'time_to_first_token_seconds': summary([
                            numeric(item.get('time_to_first_token_seconds')) for item in prompt['runs']]),
                        'prompt_tokens_per_second': summary([
                            numeric(item.get('prompt_tokens_per_second')) for item in prompt['runs']]),
                        'generation_tokens_per_second': summary([
                            numeric(item.get('generation_tokens_per_second')) for item in prompt['runs']])}
                        for prompt in run['prompts']]
                rows.append(row)
            except (ValueError, OSError):
                invalid += 1
        return {'runs': rows, 'invalid_count': invalid, 'truncated': truncated}

    def load(self, run_id):
        return self.store.load(identifier(run_id))

    def replay(self, run_id):
        from argoslive import replay
        return replay.build(self.load(run_id))

    def comparison(self, ids):
        if not 2 <= len(ids) <= 8 or len(set(ids)) != len(ids):
            raise ValueError('Select two to eight distinct runs')
        return compare([self.load(run_id) for run_id in ids])

    def experiment_comparison(self, baseline_id, candidate_id, *, allowed_intervention=None):
        baseline = self.load(baseline_id)
        candidate = self.load(candidate_id)
        from argoslive import recipe as recipe_mod
        b_std = recipe_mod.is_standard(baseline)
        c_std = recipe_mod.is_standard(candidate)
        if not b_std and c_std:
            baseline, candidate = candidate, baseline
        elif b_std == c_std and baseline.get('created', '') > candidate.get('created', ''):
            baseline, candidate = candidate, baseline
        from argoslive.results import compare_experiment
        return compare_experiment(baseline, candidate, allowed_intervention=allowed_intervention)

    def csv(self, ids):
        return export_csv(self.comparison(ids))
