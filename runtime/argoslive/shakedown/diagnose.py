"""Deterministic matcher engine: the shape of a wrong answer becomes failure codes, by code only.

`diagnose(card, item, saved_item)` reads the saved visible answer and the saved outcome of one
item and evaluates the card's matchers against them. It never rescores: an item saved as a pass
yields no codes whatever its matchers say, and a miss no matcher claims yields
`miss.unclassified`. Answers are parsed with the scorers' own parsing, so a diagnosis reads an
answer the way the score did.

The matcher set is closed (DESIGN 7.1). Each takes one argument, checked at validation time
by `check_matcher` (called from `fault.validate`):

    equals              text           the whole answer is this text (case and spacing ignored)
    choice-is           "B"            the answer is this option letter
    contains-token      text           the answer contains this word or phrase as whole words
    numeric-equals      "14"           the answer is this number
    numeric-delta       {"by": "2"}    answer minus the item's reference is exactly this
                        {"within": "1"}  the answer is off by at most this, and not exact
    json-path-mismatch  "a.0.b" or ["a", 0, "b"]
                                       the answer is JSON whose value there is absent or differs
                                       from the reference's
    tool-name-is        "read_valve"   the answer is a tool call with this name
    tool-arg-mismatch   kind, or {"kind": kind, "arg": name}
                                       the right tool, with an argument missing, extra, of the
                                       wrong type ("type") or with the wrong value ("value")
    sequence-violation  "order", "extra-step", "missing-step" or "dangling-ref"
    reply-seconds-over  30             the saved reply time is over this many seconds

A malformed answer matches nothing that needs a parsed answer; no matcher raises on one.

`document` is the document-miss diagnosis that `replay.py` shows, kept here so every miss
diagnosis lives behind this module. Its output is unchanged.
"""
from decimal import Decimal, InvalidOperation
import re

from .. import ability, doc_trial
from . import taxonomy

PASS = 'pass'
# Saved outcomes that are scored misses. Anything else (unscored, absent, unknown) is not diagnosed.
MISSES = ('wrong_answer', 'format_error')
ARG_KINDS = ('missing', 'extra', 'type', 'value')
SEQUENCE_KINDS = ('order', 'extra-step', 'missing-step', 'dangling-ref')
STEP_REF = re.compile(r'\$step([1-9][0-9]*)\.[a-z][a-z0-9_]*')
TOOL_NAME = re.compile(r'[a-z][a-z0-9_]{0,63}')
WORD = re.compile(r"[\w'-]+")
MISSING = object()


# --- reading the saved answer -------------------------------------------------------------

def _answer(saved_item):
    output = saved_item.get('output') if isinstance(saved_item, dict) else None
    if not isinstance(output, str) or len(output) > ability.LIMIT:
        return None
    return ability.answer_text(output)


def _number(text):
    try:
        return ability.numeric(text)
    except (ValueError, InvalidOperation, TypeError):
        return None


def _decimal(value):
    """A finite decimal from a matcher argument or a numeric reference, else None."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        number = Decimal(value.replace(',', ''))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _json(text):
    try:
        return ability.decode(text)
    except (ValueError, TypeError, RecursionError):
        return MISSING


def _reference(item):
    rule = item.get('scorer') if isinstance(item, dict) else None
    return rule.get('expected', MISSING) if isinstance(rule, dict) else MISSING


def _words(text):
    return WORD.findall(text.casefold())


def _path(value):
    """A path argument as a tuple of keys and indexes, or None when it is not one."""
    if isinstance(value, str):
        parts = [int(part) if part.isascii() and part.isdigit() else part for part in value.split('.')]
    elif isinstance(value, list):
        parts = value
    else:
        return None
    if not parts or any(type(part) not in (str, int) or part == '' or (type(part) is int and part < 0)
                        for part in parts):
        return None
    return tuple(parts)


def _at(value, path):
    for part in path:
        if isinstance(value, dict) and isinstance(part, str) and part in value:
            value = value[part]
        elif isinstance(value, list) and type(part) is int and part < len(value):
            value = value[part]
        else:
            return MISSING
    return value


def _same(left, right):
    """Equality that keeps true apart from 1, as the closed-schema scorer does."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _call(value):
    """A tool call as (name, arguments), or None."""
    if (isinstance(value, dict) and isinstance(value.get('name'), str)
            and isinstance(value.get('arguments'), dict)):
        return value['name'], value['arguments']
    return None


def _steps(value):
    steps = value.get('steps') if isinstance(value, dict) else None
    if not isinstance(steps, list) or not steps:
        return None
    calls = [_call(step) for step in steps]
    return None if any(call is None for call in calls) else calls


# --- the closed matcher set ---------------------------------------------------------------

def _equals(arg, text, item, saved):
    return text is not None and ' '.join(text.split()).casefold() == ' '.join(arg.split()).casefold()


def _choice_is(arg, text, item, saved):
    if text is None:
        return False
    letter = re.sub(r'^(?:answer|the answer is)\s*:?\s*', '', text, flags=re.I).strip('(). ')
    return len(letter) == 1 and letter.upper() == arg


def _contains_token(arg, text, item, saved):
    if text is None:
        return False
    words, target = _words(text), _words(arg)
    return any(words[i:i + len(target)] == target for i in range(len(words) - len(target) + 1))


def _numeric_equals(arg, text, item, saved):
    number = _number(text) if text is not None else None
    return number is not None and number == _decimal(arg)


def _numeric_delta(arg, text, item, saved):
    number = _number(text) if text is not None else None
    reference = _decimal(_reference(item))
    if number is None or reference is None:
        return False
    difference = number - reference
    if 'by' in arg:
        return difference == _decimal(arg['by'])
    return difference != 0 and abs(difference) <= _decimal(arg['within'])


def _json_path_mismatch(arg, text, item, saved):
    value = _json(text) if text is not None else MISSING
    expected = _at(_reference(item), _path(arg))
    if value is MISSING or expected is MISSING:
        return False
    found = _at(value, _path(arg))
    return found is MISSING or not _same(found, expected)


def _tool_name_is(arg, text, item, saved):
    call = _call(_json(text)) if text is not None else None
    return call is not None and call[0] == arg


def _tool_arg_mismatch(arg, text, item, saved):
    call = _call(_json(text)) if text is not None else None
    expected = _call(_reference(item))
    if call is None or expected is None or call[0] != expected[0]:
        return False
    kind, name = (arg, None) if isinstance(arg, str) else (arg['kind'], arg.get('arg'))
    given, wanted = call[1], expected[1]
    names = [name] if name is not None else sorted(set(given) | set(wanted))
    for key in names:
        if kind == 'missing' and key in wanted and key not in given:
            return True
        if kind == 'extra' and key in given and key not in wanted:
            return True
        if key in given and key in wanted:
            if kind == 'type' and type(given[key]) is not type(wanted[key]):
                return True
            if kind == 'value' and type(given[key]) is type(wanted[key]) and not _same(given[key], wanted[key]):
                return True
    return False


def _sequence_violation(arg, text, item, saved):
    steps = _steps(_json(text)) if text is not None else None
    expected = _steps(_reference(item))
    if steps is None or expected is None:
        return False
    names, wanted = [name for name, _ in steps], [name for name, _ in expected]
    if arg == 'order':
        return names != wanted and sorted(names) == sorted(wanted)
    if arg == 'extra-step':
        return len(names) > len(wanted)
    if arg == 'missing-step':
        return len(names) < len(wanted)
    # dangling-ref: a "$stepN.field" value that is malformed or does not point at an earlier step.
    for position, (_, arguments) in enumerate(steps, 1):
        for key in sorted(arguments):
            value = arguments[key]
            if isinstance(value, str) and value.startswith('$step'):
                match = STEP_REF.fullmatch(value)
                if match is None or int(match.group(1)) >= position:
                    return True
    return False


def _reply_seconds_over(arg, text, item, saved):
    seconds = saved.get('latency_seconds', saved.get('reply_seconds')) if isinstance(saved, dict) else None
    return type(seconds) in (int, float) and seconds == seconds and seconds > arg


def _is_text(value, limit=400):
    return isinstance(value, str) and bool(_words(value)) and len(value) <= limit


def _is_number(value):
    return _decimal(value) is not None


def _is_delta(value):
    return (isinstance(value, dict) and len(value) == 1 and next(iter(value)) in ('by', 'within')
            and _is_number(next(iter(value.values())))
            and ('within' not in value or _decimal(value['within']) > 0))


def _is_arg_kind(value):
    if isinstance(value, str):
        return value in ARG_KINDS
    if not isinstance(value, dict) or not {'kind'} <= set(value) <= {'kind', 'arg'} or value['kind'] not in ARG_KINDS:
        return False
    return 'arg' not in value or (isinstance(value['arg'], str) and bool(TOOL_NAME.fullmatch(value['arg'])))


def _is_seconds(value):
    return type(value) in (int, float) and value == value and 0 <= value <= 86400


# name -> (argument check, matcher). The names are exactly fault.MATCHERS.
MATCHERS = {
    'equals': (_is_text, _equals),
    'choice-is': (lambda value: isinstance(value, str) and bool(re.fullmatch(r'[A-Z]', value)), _choice_is),
    'contains-token': (_is_text, _contains_token),
    'numeric-delta': (_is_delta, _numeric_delta),
    'numeric-equals': (_is_number, _numeric_equals),
    'json-path-mismatch': (lambda value: _path(value) is not None, _json_path_mismatch),
    'tool-name-is': (lambda value: isinstance(value, str) and bool(TOOL_NAME.fullmatch(value)), _tool_name_is),
    'tool-arg-mismatch': (_is_arg_kind, _tool_arg_mismatch),
    'sequence-violation': (lambda value: isinstance(value, str) and value in SEQUENCE_KINDS, _sequence_violation),
    'reply-seconds-over': (_is_seconds, _reply_seconds_over),
}


def check_matcher(when):
    """Raise ValueError unless `when` is one known matcher with a well-formed argument."""
    if not isinstance(when, dict) or len(when) != 1:
        raise ValueError('A diagnostic needs exactly one matcher')
    name, argument = next(iter(when.items()))
    if name not in MATCHERS:
        raise ValueError(f'Unknown matcher: {name!r}')
    try:
        valid = MATCHERS[name][0](argument)
    except (TypeError, ValueError, RecursionError):
        valid = False
    if not valid:
        raise ValueError(f'Malformed argument for matcher {name}')
    return when


def matches(when, item, saved_item):
    """Does one matcher claim this saved answer? False for anything it cannot read."""
    try:
        check_matcher(when)
        name, argument = next(iter(when.items()))
        return bool(MATCHERS[name][1](argument, _answer(saved_item), item, saved_item))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, InvalidOperation, ArithmeticError):
        return False


def diagnose(card, item, saved_item):
    """Failure codes for one saved item, in card order, each at most once.

    `card` is the item's fault card, `item` the form item (its reference is read, never shown),
    `saved_item` the item as saved by the run: `outcome`, `output`, `latency_seconds`.
    """
    outcome = saved_item.get('outcome') if isinstance(saved_item, dict) else None
    if outcome not in MISSES:
        return []
    codes = []
    diagnostics = card.get('diagnostics') if isinstance(card, dict) else None
    for entry in diagnostics if isinstance(diagnostics, list) else []:
        if not isinstance(entry, dict):
            continue
        code = entry.get('code')
        if isinstance(code, str) and code not in codes and matches(entry.get('when'), item, saved_item):
            codes.append(code)
    return codes or [taxonomy.UNCLASSIFIED]


# --- document misses (shown by replay.py) -------------------------------------------------

# Diagnostic labels (added 2026-10-10). They describe a saved miss; they never change a score,
# accepted answers, suite version or qualification threshold.
DIAGNOSES = {
    'wording': ('Right meaning, rejected for wording', 'wording'),
    'unsupported_quote': ('Quote copied exactly, but it doesn’t support the answer', 'quote'),
    'quote_not_exact': ('Quote not copied exactly from the passage', 'requirement'),
    'long_answer': ('Not a short answer', 'requirement'),
    'instruction_echo': ('Copied the instructions instead of answering', 'wrong'),
    'answered_missing': ('Answered something the passage doesn’t say', 'wrong'),
    'wrong': ('Wrong answer', 'wrong'),
    'format': ('Not in the required answer format', 'format'),
}
SHORT_WORDS = 6
NEGATIONS = {'not', 'no', 'never', 'none', 'nothing'}


def contains_phrase(text, phrase):
    """Whole-word containment after the scorer's own normalization."""
    words, target = doc_trial.normal(text).split(), doc_trial.normal(phrase).split()
    return bool(target) and any(words[i:i + len(target)] == target for i in range(len(words) - len(target) + 1))


def labelled(kind, reason, checks=None):
    label, group = DIAGNOSES[kind]
    return {'reason': reason, 'diagnosis': {'kind': kind, 'label': label, 'group': group}, 'checks': checks}


def document(item, rule, passage):
    """Explain a saved document verdict with separate answer and quote checks. Never rescores."""
    category, outcome, output = item.get('category'), item.get('outcome'), item.get('output') or ''
    if category == 'summary':
        if not rule or rule.get('kind') != 'doc-summary' or 'score' not in item:
            return {'reason': 'A summary written for you to read. This suite version did not score summaries.'}
        if outcome == 'pass':
            return {'reason': 'Passed the saved two-sentence and key-fact proxy; this does not judge full summary quality.'}
        if outcome == 'format_error':
            return labelled('format', 'Not scorable: the reply did not contain exactly two sentences.')
        return {'reason': f"Wrong: fewer than {rule.get('min_facts')} listed passage facts appeared in the two-sentence summary."}
    if outcome == 'pass':
        return {'reason': {'answer': 'Correct: the answer matches the passage.',
                           'quote': 'Correct: an accepted answer, backed by a quote copied exactly from the passage.',
                           'not_stated': 'Correct: it said the passage doesn’t give this.'}.get(category, 'Correct.')}
    if outcome == 'format_error':
        return labelled('format', 'Not scorable: the reply wasn’t the required answer format, so it counts as a miss.')
    if category == 'not_stated':
        return labelled('answered_missing', 'Wrong: the passage doesn’t give this, but it answered anyway.')
    accepted = (rule or {}).get('accepted') or []
    expected = ' or '.join(f'“{a}”' for a in accepted[:3])
    try:
        value = doc_trial.parse(output)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        value = None
    if value is None or not rule:
        return {'reason': f'Wrong: expected {expected}.' if expected else 'Wrong: the answer doesn’t match the passage.'}
    answer, quote = value['answer'], value['quote']
    words = doc_trial.normal(answer).split()
    checks = {'answer_accepted': value['status'] == 'answered' and doc_trial.normal(answer) in {doc_trial.normal(a) for a in accepted},
              'answer_contains_accepted': any(contains_phrase(answer, a) for a in accepted),
              'answer_words': len(words)}
    if category == 'quote':
        exact = bool(doc_trial.collapse(quote)) and doc_trial.collapse(quote) in doc_trial.collapse(passage or '')
        checks.update(quote_exact=exact, quote_supports=doc_trial.supported(rule, value))
    shown = answer[:80]
    if 'a short answer' in doc_trial.normal(answer) or 'or an empty string' in doc_trial.normal(answer):
        return labelled('instruction_echo', f'Wrong: the answer copies the instruction text (“{shown}”) instead of answering.', checks)
    if category == 'quote' and not checks['quote_supports']:
        if not checks['quote_exact']:
            return labelled('quote_not_exact', 'Wrong: the quote isn’t copied exactly from the passage.', checks)
        return labelled('unsupported_quote', 'Wrong: the quote is copied exactly, but it doesn’t contain an accepted answer, '
                        'so it doesn’t support the answer.', checks)
    if not checks['answer_accepted'] and checks['answer_contains_accepted'] and not NEGATIONS & set(words):
        same_as_quote = category == 'quote' and doc_trial.collapse(answer) == doc_trial.collapse(quote)
        if len(words) > SHORT_WORDS or same_as_quote:
            return labelled('long_answer', f'Wrong: the task asks for a short answer, but this answer is a full sentence '
                            f'({len(words)} words). It includes an accepted answer ({expected}), which must be given on its own.', checks)
        return labelled('wording', f'Wrong as scored: “{shown}” includes the accepted answer ({expected}) but isn’t exactly it. '
                        'Answers must match word for word, ignoring case and surrounding punctuation.', checks)
    return labelled('wrong', f'Wrong: expected {expected}.' if expected else 'Wrong: the answer doesn’t match the passage.', checks)
