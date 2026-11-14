"""Descriptive matched-run comparisons for the Shakedown owner bench."""
from math import comb


ALPHA_NUMERATOR = 5
ALPHA_DENOMINATOR = 100
MAX_MORE_QUESTIONS = 10000
SPEED_MIN_RELATIVE_CHANGE = 0.03


def _sign_p_value(wins, losses):
    discordant = wins + losses
    if discordant == 0:
        return 1.0
    tail = min(wins, losses)
    probability = sum(comb(discordant, index) for index in range(tail + 1)) / (2 ** discordant)
    return min(1.0, 2 * probability)


def _score(item):
    value = item.get('score')
    if value is None:
        return None
    if type(value) is bool:
        return int(value)
    if type(value) not in (int, float) or value not in (0, 1):
        raise ValueError('Run items must have binary scores')
    return int(value)


def _shared_pairs(run_a, run_b):
    a_items, b_items = run_a.get('items'), run_b.get('items')
    if not isinstance(a_items, list) or not isinstance(b_items, list):
        raise ValueError('Runs must contain item lists')
    def item_id(item):
        value = item.get('id', item.get('item_id'))
        return value if isinstance(value, str) else None
    a = {item_id(item): item for item in a_items
         if isinstance(item, dict) and item_id(item) is not None}
    b = {item_id(item): item for item in b_items
         if isinstance(item, dict) and item_id(item) is not None}
    pairs = []
    for item_id in sorted(a.keys() & b.keys()):
        score_a, score_b = _score(a[item_id]), _score(b[item_id])
        if score_a is not None and score_b is not None:
            pairs.append((item_id, score_a, score_b))
    if not pairs:
        raise ValueError('Runs have no shared scored items')
    return pairs


def _required_extra(wins, losses, form_total, shared_count):
    discordant = wins + losses
    available = max(0, form_total - shared_count)
    if discordant == 0:
        estimate = min(MAX_MORE_QUESTIONS, available)
        return {'additional_shared_questions': estimate,
                'more_questions_note': 'too few discordant pairs to estimate' if available else
                'no additional shared questions remain in this form'}
    rate = wins / discordant
    if rate in (0, 1):
        for extra in range(1, MAX_MORE_QUESTIONS + 1):
            projected_wins = wins + (extra if rate == 1 else 0)
            projected_losses = losses + (extra if rate == 0 else 0)
            if _sign_p_value(projected_wins, projected_losses) <= ALPHA_NUMERATOR / ALPHA_DENOMINATOR:
                break
        else:
            extra = MAX_MORE_QUESTIONS + 1
    else:
        for extra in range(1, MAX_MORE_QUESTIONS + 1):
            expected_wins = round(extra * rate)
            expected_losses = extra - expected_wins
            if _sign_p_value(wins + expected_wins, losses + expected_losses) <= ALPHA_NUMERATOR / ALPHA_DENOMINATOR:
                break
        else:
            extra = MAX_MORE_QUESTIONS + 1
    if extra > available:
        return {'additional_shared_questions': available,
                'more_questions_note': 'more than this form has'}
    if extra > MAX_MORE_QUESTIONS:
        return {'additional_shared_questions': MAX_MORE_QUESTIONS,
                'more_questions_note': f'more than {MAX_MORE_QUESTIONS:,} questions at this observed rate'}
    return {'additional_shared_questions': extra, 'more_questions_note': None}


def compare(run_a, run_b):
    """Compare binary outcomes on shared questions of one exact form and slice."""
    if not isinstance(run_a, dict) or not isinstance(run_b, dict):
        raise ValueError('Runs must be objects')
    if not isinstance(run_a.get('suite_version'), str) or not run_a.get('suite_version'):
        raise ValueError('Run form version is not recorded')
    if run_a.get('suite_version') != run_b.get('suite_version'):
        raise ValueError('Runs use different form versions')
    if run_a.get('state') != 'completed' or run_b.get('state') != 'completed':
        raise ValueError('Incomplete runs are not comparable')
    slice_a = run_a.get('slice_name', run_a.get('slice', 'full'))
    slice_b = run_b.get('slice_name', run_b.get('slice', 'full'))
    if slice_a != slice_b:
        raise ValueError('Runs use different slices')
    if slice_a != 'full':
        version_a, version_b = run_a.get('slice_version'), run_b.get('slice_version')
        if not isinstance(version_a, str) or not version_a or version_a != version_b:
            raise ValueError('Runs use different slice versions')
    pairs = _shared_pairs(run_a, run_b)
    wins = sum(score_b > score_a for _, score_a, score_b in pairs)
    losses = sum(score_a > score_b for _, score_a, score_b in pairs)
    ties = len(pairs) - wins - losses
    p_value = _sign_p_value(wins, losses)
    if p_value <= ALPHA_NUMERATOR / ALPHA_DENOMINATOR and wins > losses:
        verdict = 'better'
    elif p_value <= ALPHA_NUMERATOR / ALPHA_DENOMINATOR and losses > wins:
        verdict = 'worse'
    else:
        verdict = 'too-close'
    result = {'verdict': verdict, 'shared_items': len(pairs), 'wins': wins, 'losses': losses,
              'ties': ties, 'p_value': p_value, 'test': 'two-sided exact sign test',
              'slice': slice_a, 'suite_version': run_a.get('suite_version')}
    if verdict == 'too-close':
        recorded_totals = [value for value in (run_a.get('suite_total'), run_b.get('suite_total'))
                           if type(value) is int and value >= 0]
        form_total = max([len(run_a['items']), len(run_b['items']), *recorded_totals])
        result.update(_required_extra(wins, losses, form_total, len(pairs)))
    return result


def compare_speed(run_a, run_b):
    """Compare repeated generation rates, preserving each run's spread."""
    def values(run):
        samples = run.get('measurements')
        if isinstance(samples, list):
            rates = [item.get('tokens_per_second') for item in samples if isinstance(item, dict)]
        else:
            rates = [run.get('tokens_per_second')]
        rates = [value for value in rates if type(value) in (int, float) and value > 0]
        if len(rates) < 2:
            raise ValueError('Speed verdict needs at least two recorded measurements per run')
        return [float(value) for value in rates]

    def median(items):
        ordered = sorted(items)
        middle = len(ordered) // 2
        return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2

    a, b = values(run_a), values(run_b)
    median_a, median_b = median(a), median(b)
    relative = (median_b - median_a) / median_a
    spread_a = max(a) - min(a)
    spread_b = max(b) - min(b)
    threshold = max(SPEED_MIN_RELATIVE_CHANGE, spread_a / median_a, spread_b / median_b)
    verdict = 'better' if relative > threshold else 'worse' if relative < -threshold else 'too-close'
    return {'verdict': verdict, 'relative_change': relative, 'baseline_median': median_a,
            'candidate_median': median_b, 'baseline_spread': spread_a, 'candidate_spread': spread_b,
            'measurements': {'baseline': len(a), 'candidate': len(b)}}
