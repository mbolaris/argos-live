# Auto Climb watch and recovery findings

Observed on a physical persistent boot of the OpenClaw 2026.10.1 image. The initial eight practice checks passed five; three answers lacked exact supporting quotes. No candidate gain was accepted.

The 8B acquisition ended interrupted near the advertised total. The coordinator imposes a 300-second operation limit and cancels its child when exceeded; the session duration and interrupted state are consistent with that path, but the old session did not retain the precise cancellation cause. This change preserves an explicit limit explanation for future occurrences without increasing budgets or retrying automatically.

The later 14B candidate failed on its third practice answer with assistant-error. The original 4B model was restored. The original CLI adapter discarded stderr, so that exact failure cannot be attributed confidently. Ollama logs show earlier GPU discovery watchdog timeouts; they are startup evidence, not proof of the later answer failure. Future nonzero CLI exits retain bounded stderr in an owner-only local log, never in browser responses.

Watch fixes: render actual reply.text; suppress the previous answer while the current task is pending; completed counts cannot exceed the suite total; show acquisition percentage and hide stale challenge content; explain receipt checks; show blocked/options-exhausted summaries, current kept model, and failed attempts. The user sees no claimed gain after an incomplete comparison.

Verification: Auto Climb coordinator tests, assistant-trial tests, Node presentation regressions and existing Chromium fixture browser smoke, including download and blocked mobile captures. Fixture results do not establish real model improvement, incremental streaming, physical GPU or Firefox acceptance.

Remaining product work: persistent before/after scorecard throughout the run; visible ladder movement after validated gains; narrative transitions that explain each candidate; actual incremental assistant output if the gateway supplies it. Do not animate invented tokens.
