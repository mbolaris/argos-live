# OpenClaw capabilities and addons

The distro must deliver working agent capabilities alongside model downloads and benchmarks. This is a capability plan, not an installed-addon receipt. Validate against the OpenClaw version pinned in `versions.env`; recheck inventory and API compatibility with each candidate release.

Owner decision: Ollama is the supported language-model inference backend. Use native OpenClaw Ollama integration and Ollama-managed model manifests/assets. Separate llama-cpp provider/server installation, routing and GGUF downloader work are outside this milestone. Historical source provider references remain inert; resolve model preferences to verified Ollama artifacts before activation.

## Required capability coverage

| Capability | Implementation candidate | Live acceptance |
|---|---|---|
| Local conversation and model switching | Bundled `ollama` provider | Offline reply, streaming, tool compatibility, model selection and failed-load recovery |
| Preferred models and vision | Ollama model catalog and bundled `ollama` provider | Verify exact model/quantization and vision support; test image input, GPU/offload and failed-load recovery; unresolved preferences remain pending |
| Persistent agent memory | Existing `memory-core`; local embedding provider if semantic recall is enabled | Separate agent state; recall after reboot; offline retrieval; report unavailable embeddings rather than require a cloud account |
| Browser tasks | Bundled `browser` plugin plus a supported Linux browser runtime | Actual navigation and a controlled tool test; denied for chat-only profiles; isolated browser profile |
| Local document input | Bundled `document-extract` candidate plus required format dependencies | Extract a sample PDF/text document; distinguish text extraction from model vision |
| Voice output | Bundled `tts-local-cli` plus a pinned Linux speech engine and voice assets | Generate and play a short local sample offline; show missing audio devices/dependencies |
| Voice input | Compatible local transcription provider/helper to be selected | Record/transcribe a supplied sample offline; tested Linux audio/codec/model dependencies; no inherited Windows commands |
| Image creation | Compatible Linux local image backend and OpenClaw adapter to be selected | One controlled generation; progress, VRAM coexistence and unloading; no cloud fallback without configuration |
| Skills and delegated model consultation | Reviewed skill definitions plus their declared and observed dependencies | Skill eligibility, required executable/tool/provider checks, denied-tool tests and actual result from the intended model |
| Optional messaging channels | Bundled `telegram` or another selected channel plugin | Separate owner setup and credentials; not required for offline first chat |

Bundled/external classifications above come from the [pinned v2026.9.7 inventory](https://github.com/openclaw/openclaw/blob/v2026.9.7/docs/plugins/plugin-inventory.md). Availability in upstream is not evidence the image has loaded or successfully exercised a capability. Advanced memory engines and additional channel providers remain optional; do not add them merely to increase the addon count.

## Lifecycle and readiness

For every supported addon, retain a generic catalog record: capability ID, plugin/package ID, bundled versus external distribution, exact version/revision and integrity, compatible host version, license/notices, Linux executables/assets, network/credential needs, tool grants, storage locations and acceptance/rollback evidence. No floating `latest` installations in image builds. Bundled code follows the pinned host release; external plugins need independent discovery and candidate testing.

Display separate states for available, installed, dependency missing, credentials needed, disabled by policy, testing, ready and failed. Include useful reasons and the next setup action. A copied SKILL.md, installed npm package or loaded manifest cannot by itself establish readiness. Check dependencies, effective per-agent tool permissions and an actual controlled capability invocation. Skill eligibility depends on platform, binaries, environment and config; see [pinned skills documentation](https://github.com/openclaw/openclaw/blob/v2026.9.7/docs/tools/skills.md).

Keep personality transfer narrow. Resolve addon dependencies on Live, without cloning source permissions, tokens, channel bindings or executable helpers. Argos can receive the broadest explicitly selected access; Nyx and Proteus keep independent policies. The generic starter remains conversation-only until a capability profile is selected. Installing an addon must not silently widen every agent's tool access.

Configure local inference/media services on loopback. Keep private settings and credentials in encrypted persistence; model assets may use owner-selected DATA with its encryption status visible. Keep basic chat available when optional providers fail. For GPU-heavy image/voice/model jobs, test resource coordination rather than running all backends simultaneously by default.

Inspect registration and exercise the running gateway separately. Pin/review code before runtime inspection because inspection can load it. Preserve a private target snapshot before changes and verify rollback. Follow the [pinned plugin lifecycle documentation](https://github.com/openclaw/openclaw/blob/v2026.9.7/docs/tools/plugin.md).

## Release gate

Each claimed feature must have a capability smoke test and a documented offline/online boundary. Run addon inventory, dependency and license audits alongside core runtime update checks. Exercise supported capabilities against the candidate OpenClaw release, then restore a known-good target profile. Retain exact package/backend/asset versions in release manifests. Physical audio, GPU and browser acceptance stays separate from fixture success. Unsupported features remain visibly pending, not advertised as ready.
