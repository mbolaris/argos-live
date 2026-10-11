# Live UI review — October 11, 2026

## What the owner saw

Actual Toronado Firefox showed “Ready to prove I can do better?”, a generic GO button next to “Talk to Argos”, and a saved 20/24 reading result. The juxtaposed buttons read like “Go talk to Argos”. The page did not make the improvement round tangible.

## Deployment finding

Read-only SSH inspection confirmed that persistent runtime files shadow the new PR91 image. The merged server, index.html, app.js, and style.css match the persistent upper copies and differ from the squashfs lower copies. Persisted assistant_trial.py and other backend modules also exist. The new USB write and ciphertext verification succeeded, but this does not establish the running app version. No remote runtime or user state was changed during this review.

Before further physical acceptance: inventory every tracked runtime file in merged/lower/upper layers; compare the lower against the exact verified image source; preserve a rollback copy of all differing distro-owned files; verify no active benchmark/trial/pull; refresh the distro runtime coherently; restart and verify served assets plus backend source hashes. Preserve saved results, selected models, storage settings, assistant instructions, and the owner’s document edit. Never blindly delete the persistent layer. Capture the actual Firefox screen with browser chrome/session credentials excluded from shared artifacts.

Future USB acceptance must include the merged runtime after a persistent boot, not only ISO bytes and guest-mode tests. The existing image_refresh module refreshes command shims only; runtime migration remains necessary.

## Immediate UI changes

The primary button now names its action: Start reading challenge, Start improvement round, Watch live answers, or Review the result. Chat is a separate area below a divider, labeled Open chat. The improvement offer headline describes the task rather than asking whether the agent can prove itself.

## Next experience gate

Watch a real GPU-backed improvement round end to end. The watch screen should make the current question, live answer, answer verdict, and before/after difference dominant. Show one clear outcome (better, no clear gain, or stopped) and one next action. Never invent a model opinion or imply that a fixture, a lab-only recipe, or one noisy retest establishes everyday assistant improvement. This UI patch alone does not establish that the experience is fun or complete.
