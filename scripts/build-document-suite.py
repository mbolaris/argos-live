#!/usr/bin/env python3
"""Regenerate the original short-document suite. Passages are written for this project.

Every name, number and fact below is invented. Changing any passage, question,
accepted answer or criterion requires bumping VERSION, because results from
different suite versions are never ranked together.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from argoslive import doc_trial  # noqa: E402

VERSION = '1.0.0'
OUTPUT = Path(__file__).resolve().parents[1] / 'runtime/argoslive/data/documents/short.json'

CRITERIA = {
    'version': 1,
    'description': 'Fixed before any model is scored. A baseline is for comparison only; it never moves these bars.',
    'min_correct': {'answer': 7, 'quote': 6, 'not_stated': 7},
    'max_format_errors': 2,
}

PASSAGES = [
    {'id': 'ferry',
     'text': ('The Larkspur Harbor ferry began service on 4 March 1987. Two vessels, the Marigold and the Heron, '
              'share the route. The Marigold carries up to 240 passengers and 18 cars, while the Heron carries 180 '
              'passengers and no cars. Crossings take 35 minutes. In winter the first departure leaves at 6:40 in the '
              'morning and the last at 8:15 in the evening. Fares are $6 for adults and $3 for children under twelve; '
              'bicycles ride free. The harbor authority reviews fares every three years, and the most recent review '
              'kept prices unchanged.'),
     'answer': ('How many passengers can the Marigold carry?', ['240', '240 passengers']),
     'quote': ('How long does a crossing take?', ['35 minutes', '35'], 'Crossings take 35 minutes.'),
     'not_stated': 'What is the fare for a senior citizen?',
     'summary': 'Summarize this passage in two sentences.'},
    {'id': 'library',
     'text': ('The Orchard Street Library will close for renovation on 1 June and reopen on 15 September. During the '
              'closure, borrowers may return books at the Millbrook branch, which will extend its weekend hours to '
              'six in the evening. Holds placed before the closure will transfer to Millbrook automatically. The '
              'renovation adds a quiet reading room on the second floor, replaces the heating system, and widens the '
              'main entrance for wheelchair access. The project is funded by a $1.2 million bond approved by voters '
              'last November. Fines will not be charged for items due during the closure.'),
     'answer': ('When will the library reopen?', ['15 September', 'september 15', '15 sept']),
     'quote': ('How much is the bond that funds the project?', ['$1.2 million', '1.2 million'],
               'The project is funded by a $1.2 million bond approved by voters last November.'),
     'not_stated': 'Who is the architect of the renovation?',
     'summary': 'Summarize this notice in two sentences.'},
    {'id': 'returns',
     'text': ('Kestrel Outdoor accepts returns within 45 days of purchase when the item is unused and in its original '
              'packaging. Refunds go back to the original payment method within seven business days after the item '
              'arrives at the warehouse. Return shipping is free for orders over $75; smaller orders pay a flat $8 '
              'shipping fee. Items marked Final Sale, including all tents and sleeping bags, cannot be returned. '
              'Exchanges for a different size are handled by phone, and the exchange window is 30 days.'),
     'answer': ('Within how many days of purchase must an item be returned?', ['45', '45 days']),
     'quote': ('What is the flat shipping fee for returns on smaller orders?', ['$8', '8 dollars'],
               'Return shipping is free for orders over $75; smaller orders pay a flat $8 shipping fee.'),
     'not_stated': 'Does Kestrel Outdoor offer gift wrapping?',
     'summary': 'Summarize this return policy in two sentences.'},
    {'id': 'minutes',
     'text': ('The garden committee met on Tuesday with five members present. Priya reported that the rainwater tanks '
              'are installed and holding 2,000 liters. The committee voted four to one to buy raised beds for the '
              'east lawn rather than repair the old shed. Marcus will collect quotes from three suppliers by the end '
              'of the month. The spring planting day was set for 12 April, and volunteers should bring their own '
              'gloves. Next month the committee will decide how to divide the plots among families.'),
     'answer': ('How many liters do the rainwater tanks hold?', ['2,000', '2000', '2,000 liters', '2000 liters']),
     'quote': ('Who will collect quotes from suppliers?', ['marcus'],
               'Marcus will collect quotes from three suppliers by the end of the month.'),
     'not_stated': 'How much money does the committee have in its budget?',
     'summary': 'Summarize these meeting minutes in two sentences.'},
    {'id': 'trail',
     'text': ('The Cedar Ridge loop is a 7.5 kilometer trail with 320 meters of climbing. Most hikers finish it in '
              'about three hours. The trailhead parking lot holds 40 cars and fills early on weekends. Dogs are '
              'allowed on a leash, but the lookout at the halfway point is closed to dogs from March to June to '
              'protect nesting birds. There is no drinking water along the route, so hikers should carry at least two '
              'liters. The trail is closed after heavy snow, and the ranger station posts closures by 7 a.m.'),
     'answer': ('How long is the Cedar Ridge loop in kilometers?', ['7.5', '7.5 kilometers', '7.5 km']),
     'quote': ('Why is the lookout closed to dogs from March to June?', ['nesting birds', 'protect nesting birds'],
               'Dogs are allowed on a leash, but the lookout at the halfway point is closed to dogs from March to '
               'June to protect nesting birds.'),
     'not_stated': 'Is camping allowed along the trail?',
     'summary': 'Summarize this trail description in two sentences.'},
    {'id': 'museum',
     'text': ('The Tidewater Museum opens its new exhibit, Salt and Sail, on 8 October. The exhibit follows how coastal '
              'towns traded salt across the bay in the nineteenth century. It includes a restored cargo boat, a '
              'working salt press, and more than 200 letters written by ship captains. Admission is $12 for adults '
              'and free for members and for children under six. Guided tours run at 11 a.m. and 2 p.m. on weekends '
              'and must be booked online. The exhibit closes on 31 January.'),
     'answer': ('When does the Salt and Sail exhibit open?', ['8 october', 'october 8', '8 oct']),
     'quote': ('What does the exhibit show about the nineteenth century?', ['trade', 'traded salt', 'salt across the bay'],
               'The exhibit follows how coastal towns traded salt across the bay in the nineteenth century.'),
     'not_stated': 'Who restored the cargo boat?',
     'summary': 'Summarize this announcement in two sentences.'},
    {'id': 'release',
     'text': ('Version 3.2 of the Quillnote app adds offline editing, so notes can be changed without a connection and '
              'sync when the device is back online. Search is now twice as fast on libraries above 10,000 notes. The '
              'release removes the old plain-text export; users should choose Markdown export instead. A bug that '
              'duplicated checklist items after a sync conflict is fixed. Version 3.2 requires Android 10 or newer. '
              'Support for Android 8 and 9 ended with version 3.1.'),
     'answer': ('Which Android version or newer does Quillnote 3.2 require?', ['android 10', '10']),
     'quote': ('What replaced the old plain-text export?', ['markdown'],
               'The release removes the old plain-text export; users should choose Markdown export instead.'),
     'not_stated': 'How much does Quillnote cost?',
     'summary': 'Summarize these release notes in two sentences.'},
    {'id': 'bakery',
     'text': ('Sunrise Bakery bakes its sourdough in batches of 24 loaves, starting at four in the morning. The starter '
              'is fed twice a day and has been kept alive since the bakery opened in 2009. Loaves sell for $7, or $6 '
              'each when a customer buys three or more. Unsold bread is donated to the Eastside Pantry every evening '
              'at closing. The bakery is closed on Mondays. Custom orders for more than ten loaves need two days of '
              'notice.'),
     'answer': ('How many loaves are in each batch of sourdough?', ['24', '24 loaves']),
     'quote': ('What happens to unsold bread?', ['donated', 'donated to the eastside pantry'],
               'Unsold bread is donated to the Eastside Pantry every evening at closing.'),
     'not_stated': 'Does the bakery sell gluten-free bread?',
     'summary': 'Summarize this description of the bakery in two sentences.'},
]

INSTRUCTION = ('Read the passage and answer using only the passage. Do not use outside knowledge.\n\n'
               'PASSAGE:\n{passage}\n\nQUESTION: {question}\n\n'
               'Respond with only a JSON object with exactly these keys: '
               '{{"status": "answered" or "not_stated", "answer": "a short answer, or an empty string", '
               '"quote": "one sentence copied exactly from the passage that supports the answer, or an empty string"}}. '
               'If the passage does not contain the answer, use status "not_stated" with an empty answer and quote.')

SUMMARY_PROMPT = 'Read the passage.\n\nPASSAGE:\n{passage}\n\n{question} Use only the passage.'


def build():
    items = []
    for number, passage in enumerate(PASSAGES, 1):
        key = f'{number:02d}'
        text = passage['text']
        question, accepted = passage['answer']
        items.append({'id': f'answer-{key}', 'passage_id': passage['id'], 'category': 'answer', 'scored': True,
                      'question': passage['answer'][0],
                      'prompt': INSTRUCTION.format(passage=text, question=question),
                      'scorer': {'kind': 'doc-answer', 'accepted': accepted, 'passage': text}})
        question, accepted, quote = passage['quote']
        items.append({'id': f'quote-{key}', 'passage_id': passage['id'], 'category': 'quote', 'scored': True,
                      'question': passage['quote'][0],
                      'prompt': INSTRUCTION.format(passage=text, question=question),
                      'scorer': {'kind': 'doc-quote', 'accepted': accepted, 'passage': text,
                                 'reference_quote': quote}})
        items.append({'id': f'missing-{key}', 'passage_id': passage['id'], 'category': 'not_stated', 'scored': True,
                      'question': passage['not_stated'],
                      'prompt': INSTRUCTION.format(passage=text, question=passage['not_stated']),
                      'scorer': {'kind': 'doc-not-stated', 'passage': text}})
    for number, passage in enumerate(PASSAGES, 1):
        items.append({'id': f'summary-{number:02d}', 'passage_id': passage['id'], 'category': 'summary',
                      'scored': False, 'question': passage['summary'],
                      'prompt': SUMMARY_PROMPT.format(passage=passage['text'], question=passage['summary']),
                      'scorer': {'kind': 'doc-summary'}})
    for item in items:
        doc_trial.add_fixtures(item)
    return {'schema': 'argos-document-suite/1', 'suite': 'short', 'version': VERSION, 'license': 'MIT',
            'source': 'original-argos-live', 'context': doc_trial.CONTEXT,
            'omitted_categories': ['long-documents', 'file-reading'], 'criteria': CRITERIA,
            'items': items}


def main():
    data = build()
    doc_trial.validate(data)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {len(data["items"])} items to {OUTPUT}')


if __name__ == '__main__':
    main()
