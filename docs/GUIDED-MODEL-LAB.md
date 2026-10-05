# Guided model lab

The desktop dashboard should guide the owner through a useful goal, a baseline,
a model or capability upgrade, and measured results. Chat alone does not teach
the owner how to grow the assistant.

The managed dashboard now offers **Pause chat and test this model**. It pauses
the desktop-owned assistant, verifies the configured model source, starts an
owned isolated Ollama service, runs `speed/1` with the short prompt (one load/
warmup and three measured replies), then `ability/quick/1.0.0`. Results use the
existing private store and remain comparable with matching CLI runs. The prior
assistant startup is requested after cleanup; returning to ready is observed
separately, and the lab stays visible. An initially stopped assistant stays stopped.

Progress shows the current phase and scored task count. Cancel keeps completed
results and releases the owned backend before assistant restart. Requests have a
120-second read timeout; batches request cancellation after 15 minutes. An
in-flight read and cleanup can outlast cancellation. Cancellation is not an
instant completion promise. No unrelated daemon is adopted, no model is
downloaded, and agent permissions/configuration are not changed.

Output tokens/s, prompt processing tokens/s and first-token latency are displayed
separately from task accuracy and format errors. Startup warmup is a short sample,
not a repeated speed benchmark. Repeated prompt processing can reuse cached
prefixes. Tokenizer differences limit comparisons between model families. The
quick suite does not establish general competence, coding execution or real
tool use. Capability cards provide concrete setup/test guidance without claiming
untested addons ready.

This slice tests the **configured** source/model. Choosing downloaded models,
guided verified downloads, configuring addons, richer skill/tool acceptance,
before/after charts, thermal policy, live per-conversation rates, and hardware-
aware persona integration remain separate work. The lab needs native Linux,
browser, image and physical acceptance before being described as shipped.
