# Document trial miss audit — 2026-10-10

Scope: every miss in the ten complete `documents/short/1.0.0` runs saved on Toronado: seven `qwen3:4b-instruct-2507-q4_K_M` runs (five standard, two with the strict-format lab instruction) and three older `qwen3:0.6b` runs. The suite is public and original (MIT); the passages, questions and accepted answers below are quoted from `runtime/argoslive/data/documents/short.json`. Model outputs are the saved responses.

Nothing in this audit changes a score, an accepted answer, the suite version or a qualification threshold. Saved runs keep their original verdicts and labels.

## The rule being audited

Every reading prompt ends with the same explicit response contract:

> `"answer": "a short answer, or an empty string"`, `"quote": "one sentence copied exactly from the passage that supports the answer, or an empty string"`

The scorer (`doc_trial.score`) marks a quote question correct only if **both** hold:

1. **Answer accepted:** the answer, after lowercasing, collapsing spaces and trimming surrounding punctuation, is *exactly* one of the accepted answers.
2. **Quote supports:** the quote (1–300 characters) appears verbatim in the passage **and** contains an accepted answer.

So the old label "Show the evidence" / "Supported quotations" could fail on wording alone with perfect evidence. An exact quote by itself is not evidence the answer was right: the quote can be exact and still not contain the answer, or the answer can be a different fact.

## Classes

Each miss is checked separately for answer acceptance and quote validity, then labeled (`runtime/argoslive/replay.py::diagnose`). Labels are diagnostic, shown as "Diagnostic label (new, not a score)".

| Class | Label shown | Test |
|---|---|---|
| Correct meaning rejected for wording | Right meaning, rejected for wording | Answer not accepted; contains an accepted answer as whole words; at most 6 words; no negation; for quote questions the quote is exact and contains an accepted answer. Flags a candidate for human review, not proof. |
| Exact quotation that does not support the answer | Quote copied exactly, but it doesn't support the answer | Quote verbatim in the passage but contains no accepted answer. |
| Genuinely wrong | Wrong answer · Copied the instructions instead of answering · Answered something the passage doesn't say | Anything else, including answers that echo the prompt's placeholder text, and "not stated" questions answered with content. |
| Valid answer violating an explicit requirement | Not a short answer · Quote not copied exactly from the passage | Answer contains an accepted answer but is a full sentence (more than 6 words, or identical to the quote); or the quote is not verbatim. |
| Format | Not in the required answer format | Not the closed JSON object; scored as a format error. |

## qwen3:4b — 30 miss instances over 7 runs; all are answer-field misses

Every quote in every 4B miss was copied exactly and contained an accepted answer. No miss was a wrong fact or an unsupported quote. I reviewed each by hand against the passage; the meaning of every answer below is correct.

| Item | Question | Accepted | Answer given | Quote valid | Runs | Class |
|---|---|---|---|---|---|---|
| quote-05 | Why is the lookout closed to dogs from March to June? | "nesting birds", "protect nesting birds" | "to protect nesting birds" | yes | 7 | Right meaning, rejected for wording |
| quote-07 | What replaced the old plain-text export? | "markdown" | "Markdown export" | yes | 7 | Right meaning, rejected for wording |
| answer-07 | Which Android version or newer does Quillnote 3.2 require? | "android 10", "10" | "Android 10 or newer" | (not scored) | 2, strict-format only | Right meaning, rejected for wording |
| quote-06 | What does the exhibit show about the nineteenth century? | "trade", "traded salt", "salt across the bay" | "The exhibit shows how coastal towns traded salt across the bay in the nineteenth century." (15 words, paraphrases "follows") | yes | 7 | Not a short answer |
| quote-08 | What happens to unsold bread? | "donated", "donated to the eastside pantry" | "Unsold bread is donated to the Eastside Pantry every evening at closing." (identical to its quote) | yes | 7 | Not a short answer |

Totals: 16 wording, 14 not-a-short-answer, 0 unsupported quote, 0 wrong, 0 format. Observation: quote-05's quote is a clause, not the full passage sentence; the contract says "one sentence" but the scorer accepts any verbatim substring, so this is not counted against it.

Consequence: the 4B model's "Correct answers with a supporting quote 4/8 (needs 6)" is limited by how it fills the answer field, not by finding or quoting evidence. The strict-format instruction ("Follow the requested output format; omit extra prose") did not change these four quote misses and added the answer-07 wording miss.

## qwen3:0.6b — 39 miss instances over 3 runs; mostly genuinely wrong

| Example | Answer / quote | Class |
|---|---|---|
| answer-03 "Within how many days of purchase must an item be returned?" (accepted "45") | "30", quoting the 30-day *exchange* sentence | Wrong answer — the quote is exact and contains "30", which is why an exact quote alone is not enough |
| quote-02, quote-03, quote-06 | "a short answer, or an empty string" | Copied the instructions instead of answering |
| missing-01/02/03/08 | answered with placeholder text where the passage says nothing | Answered something the passage doesn't say |
| quote-07 | "Markdown" with quote "A bug that duplicated checklist items after a sync conflict is fixed." | Quote copied exactly, but it doesn't support the answer |
| quote-05, quote-08 (some runs) | full-sentence answers; quotes not verbatim | Not a short answer · Quote not copied exactly |
| missing-02, missing-06 | duplicated JSON keys, unclosed objects | Not in the required answer format |

Totals: 23 genuinely wrong (incl. 9 instruction echoes and 11 answered-missing), 3 wording, 2 long answers, 4 quote not exact, 3 unsupported quotes, 4 format.

## What changed in the product (display only)

- The combined check is shown as **"Correct answers with a supporting quote"** and the category as **"Answer with a supporting quote"**. Saved runs still contain "Supported quotations"; the rename happens when displaying.
- The replay shows the separate checks for each miss (answer accepted · quote copied exactly · quote contains an accepted answer), the diagnostic label marked "new, not a score", and a per-run breakdown of why answers missed.
- Regression tests: `tests/test_replay.py::AuditTests` replays real receipts from this audit and asserts both the unchanged scorer verdict and the diagnostic class.
- `scripts/audit-document-misses.py RESULTS_DIR` regenerates this table from any results directory.

## Proposed next experiment (not implemented)

Smallest change that targets the measured miss pattern, and what it can and cannot show:

- **Change:** one lab instruction that restates the contract the prompt already gives, without any answer strings: *"In "answer", give only the shortest phrase from the passage that answers the question; put the full supporting sentence in "quote"."*
- **Why this one:** all 30 qwen3:4b miss instances are answer-field form (16 wording, 14 full-sentence answers); its quotes are already valid. The existing strict-format instruction does not address answer length.
- **Matched retest:** the same model, suite version 1.0.0, passages, scorer and thresholds; compare per item with the replay, reporting wording and long-answer counts separately from correct-answer counts.
- **Honest reading of a result:** a gain would show the model can follow this suite's short-answer contract when reminded. It is test-format compliance for this suite, not better reading or general intelligence, and it says nothing about the everyday assistant (U10). A gain driven only by wording should be reported as such.
- **Not proposed:** adding accepted variants or relaxing matching. That is a separately versioned suite decision for the owner (U12 option 2), never mixed into an experiment comparison.
