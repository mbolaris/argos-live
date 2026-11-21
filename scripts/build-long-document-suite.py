#!/usr/bin/env python3
"""Build the original long-document evaluation form from fixed project records."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import doc_trial

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.0'
OUTPUT = ROOT / 'runtime/argoslive/data/documents/long.json'
INSTRUCTION = ('Read the passage and answer using only the passage. Do not use outside knowledge.\n\n'
               'PASSAGE:\n{passage}\n\nQUESTION: {question}\n\n'
               'Respond with only a JSON object with exactly these keys: '
               '{{"status": "answered" or "not_stated", "answer": "a short answer, or an empty string", '
               '"quote": "one sentence copied exactly from the passage that supports the answer, or an empty string"}}. '
               'If the passage does not contain the answer, use status "not_stated" with an empty answer and quote.')
SUMMARY_PROMPT = 'Read the passage.\n\nPASSAGE:\n{passage}\n\n{question} Use only the passage.'
CRITERIA = {
    'version': 1,
    'description': ('Fixed before scoring. Each category requires at least five correct answers; summaries '
                    'check exactly two sentences and at least two listed facts, not full summary accuracy.'),
    'min_correct': {'answer': 5, 'quote': 5, 'not_stated': 5, 'summary': 5},
    'max_format_errors': 6,
}

RECORDS = [
    ('harbor', 'Larkspur Harbor', 'the east pier replacement', '14 May 2026', '30 September',
     '12 segments', '48 meters', 'Northline Works', 'four review stages', '$840,000', '10 August',
     'inspect the underwater anchors before any crane lift'),
    ('archive', 'Morrow County Archive', 'the climate-control upgrade', '2 February 2026', '18 June',
     'six rooms', '19 degrees Celsius', 'Blue Ledger Services', 'three humidity surveys', '$126,500', '1 April',
     'move photographs only after the room log is signed'),
    ('clinic', 'Juniper Street Clinic', 'the evening intake pilot', '7 March 2026', '12 July',
     'four intake desks', '22 appointments per shift', 'Cedar Health Cooperative', 'two staffed shifts', '$94,200', '20 May',
     'urgent referrals remain with the existing triage team'),
    ('rail', 'Westmere Transit Office', 'the platform-signage refresh', '11 January 2026', '4 October',
     'nine platforms', '1.8 meters', 'Lantern Signworks', 'five passenger checks', '$312,000', '16 June',
     'the north platform stays open during installation'),
    ('garden', 'Redfern Community Garden', 'the water-meter trial', '21 April 2026', '15 August',
     'seven plots', '2,400 liters', 'Mosaic Utility Lab', 'three weekly readings', '$18,750', '2 June',
     'manual readings continue until two consecutive uploads match'),
    ('museum', 'Bellwether Museum', 'the storage-room inventory', '9 February 2026', '22 November',
     'eleven cabinets', '16 items per tray', 'Paper Kite Records', 'four catalogue passes', '$57,600', '3 September',
     'a second reviewer signs any item marked condition-uncertain'),
    ('school', 'Elm Crossing School', 'the library lending change', '5 March 2026', '2 September',
     'eight classes', 'three books per pupil', 'Open Shelf Network', 'two return checks', '$41,300', '12 May',
     'students with an unresolved return keep the old limit'),
    ('water', 'Pine Vale Water Board', 'the pump inspection cycle', '17 January 2026', '8 December',
     'five pumps', 'six hours', 'Clear Current Engineering', 'three pressure readings', '$203,400', '29 July',
     'a pump is isolated only after the backup line is confirmed'),
    ('market', 'North Quay Market', 'the vendor permit renewal', '1 April 2026', '31 October',
     '38 stalls', 'two meters', 'Common Ground Office', 'four document checks', '$26,800', '9 July',
     'a late insurance certificate pauses only that vendor application'),
    ('library', 'Ashdown Mobile Library', 'the route-planning trial', '3 February 2026', '14 September',
     'six rural stops', '35 minutes', 'Fieldnote Mobility', 'five driver logs', '$72,900', '27 May',
     'weather closures are recorded as skipped stops, not missed service'),
]


def passage_for(row):
    (slug, organization, project, start, finish, quantity, measure, supplier,
     review_stages, budget, deadline, exception) = row
    return (
        f'{organization} approved {project} on {start}. The work plan lists {quantity}, with a design '
        f'limit of {measure}. The approval record names {supplier} as the delivery partner and sets a '
        f'not-to-exceed budget of {budget}. The team expects the work to finish by {finish}, but the '
        f'date is a planning target rather than a guarantee. A readiness review is due {deadline}; it '
        f'must be complete before the next scheduled phase can begin.\n\n'
        f'The project office divided the work into {review_stages}. Staff record each decision in the '
        f'weekly register, including the date, the responsible role, and any unresolved dependency. '
        f'The register is authoritative when a slide deck or email gives a different estimate. A '
        f'change to the budget or delivery date requires a signed change note from both the project '
        f'lead and the finance reviewer. Draft notes are useful for discussion but do not alter the '
        f'approved plan. The supplier reports progress every second Friday. Those reports count as '
        f'evidence only after the project office checks the attached measurement sheet.\n\n'
        f'The team will compare the recorded quantity against the installed work at each checkpoint. '
        f'If a measurement falls outside the stated limit, the reviewer marks the register for follow-up '
        f'instead of averaging it with earlier readings. A missed checkpoint remains open until a new '
        f'measurement is recorded. The project lead can reorder noncritical tasks, but may not waive '
        f'the signed-change process or substitute a different supplier without approval. The final '
        f'review checks the register, the measurement sheets, and the closeout receipt as separate '
        f'records; a completed receipt alone does not prove that every checkpoint passed.\n\n'
        f'One exception is explicit: {exception.capitalize()}. The exception applies only to this '
        f'project and does not change the general review sequence. The public summary should distinguish '
        f'completed work from planned work and should name any open dependency without guessing at its '
        f'cause. No record in the approved plan identifies the project sponsor by personal name, and '
        f'the office has not published a per-checkpoint cost breakdown.\n\n'
        f'The administrative packet also describes how the team communicates status. The coordinator '
        f'posts a short update after each review, but the update is a navigation aid and never replaces '
        f'the weekly register. Readers should use the register for approved values and the measurement '
        f'sheets for observations. When the two records conflict, staff preserve both entries and open '
        f'a follow-up; they do not silently edit one to match the other. A closeout note is prepared '
        f'only after the final receipt and the outstanding-dependency list have been reviewed together. '
        f'The packet does not authorize work beyond the stated budget or finish date.'
    )


def build():
    items = []
    for number, row in enumerate(RECORDS, 1):
        slug, _organization, project, start, finish, quantity, measure, supplier, stages, budget, deadline, exception = row
        passage = passage_for(row)
        partition = 'practice' if number <= 5 else 'heldout'
        common = {'passage': passage, 'partition': partition}
        questions = [
            {'id': f'answer-{number:02}', 'category': 'answer',
             'question': f'What readiness-review deadline is recorded for {project}?',
             'scorer': {'kind': 'doc-answer', 'accepted': [deadline, deadline.replace(' ', ' '),
                                                          deadline.split()[-1]], **common}},
            {'id': f'quote-{number:02}', 'category': 'quote',
             'question': f'Which exact condition applies to {project}?',
             'scorer': {'kind': 'doc-quote', 'accepted': [exception.lower(), exception.split()[-1].lower()],
                        'reference_quote': exception[0].upper() + exception[1:] + '.', **common}},
            {'id': f'missing-{number:02}', 'category': 'not_stated',
             'question': f'What is the project sponsor’s personal name for {project}?',
             'scorer': {'kind': 'doc-not-stated', **common}},
            {'id': f'summary-{number:02}', 'category': 'summary',
             'question': f'Summarize the approved plan for {project} in two sentences.',
             'scorer': {'kind': 'doc-summary', 'required_facts': [
                 [project], [quantity], [measure], [supplier], [budget], [deadline],
                 ['weekly register'], ['signed change note'], ['planning target']],
                 'min_facts': 2, **common}},
        ]
        for item in questions:
            item.update(passage_id=slug, scored=True, prompt=(
                INSTRUCTION.format(passage=passage, question=item['question'])
                if item['category'] != 'summary' else
                SUMMARY_PROMPT.format(passage=passage, question=item['question'])))
            doc_trial.add_fixtures(item)
            items.append(item)
    return {'schema': 'argos-document-suite/1', 'suite': 'long', 'version': VERSION,
            'license': 'MIT', 'source': 'original-argos-live', 'context': doc_trial.CONTEXT,
            'omitted_categories': ['file-reading'], 'criteria': CRITERIA, 'items': items}


def main():
    data = build()
    doc_trial.validate(data)
    OUTPUT.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))
    print(f'Wrote {len(data["items"])} items to {OUTPUT}')


if __name__ == '__main__':
    main()
