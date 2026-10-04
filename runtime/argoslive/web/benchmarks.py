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
                else:
                    from argoslive.bench_speed import numeric, summary
                    row['summary'] = [{'size': prompt['size'], 'skipped': prompt['skipped'],
                        'generation_tokens_per_second': summary([
                            numeric(item.get('generation_tokens_per_second')) for item in prompt['runs']])}
                        for prompt in run['prompts']]
                rows.append(row)
            except (ValueError, OSError):
                invalid += 1
        return {'runs': rows, 'invalid_count': invalid, 'truncated': truncated}

    def load(self, run_id):
        return self.store.load(identifier(run_id))

    def comparison(self, ids):
        if not 2 <= len(ids) <= 8 or len(set(ids)) != len(ids):
            raise ValueError('Select two to eight distinct runs')
        return compare([self.load(run_id) for run_id in ids])

    def csv(self, ids):
        return export_csv(self.comparison(ids))
