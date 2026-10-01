# Software selection and redistribution

Upstream checked October 1, 2026. Exact primary runtime pins are in `versions.env`.

| Component | Pin | License / status | Primary source |
|---|---|---|---|
| Debian | trixie, snapshot 20261001T000000Z | Per-package licenses, image copyright archive | https://www.debian.org/releases/ |
| live-build | Builder version recorded by dpkg; target packages snapshot-pinned | GPL-2+ | https://packages.debian.org/trixie/live-build |
| OpenClaw | 2026.9.7, npm sha512 integrity + transitive lock | MIT; dependencies have separate licenses | https://github.com/openclaw/openclaw/tree/v2026.9.7 |
| Node | 26.10.0, upstream SHA256 | MIT with bundled third-party notices | https://nodejs.org/dist/v26.10.0/ |
| Ollama | 0.35.0, GitHub release SHA256 | MIT application; bundled CUDA libraries have NVIDIA terms | https://github.com/ollama/ollama/releases/tag/v0.35.0 |
| NVIDIA Debian driver | 550.163.01-2 | Proprietary NVIDIA components + separately licensed packaging/kernel code | https://packages.debian.org/trixie/nvidia-driver |
| QEMU | Installed Ubuntu package recorded locally | GPL-2 with component exceptions | https://www.qemu.org/docs/master/system/invocation.html |
| Tiny model | qwen3:0.6b, manifest SHA256 7df6b6e09427a769808717c0a93cadc4ae99ed4eb8bf5ca557c90846becea435 | Apache-2.0; registry license included | https://huggingface.co/Qwen/Qwen3-0.6B |

Debian current stable is 13.7. The fixed package snapshot is used instead of floating `stable` or a point-release promise. Package hashes are checked by APT signed metadata. Preserve the generated package manifest, upstream notices, Node LICENSE, OpenClaw LICENSE, and Ollama NVIDIA library notices with distributed images.

OpenClaw's tagged package requires Node >=24.16 <25 or >=26.1; selected Node 26.10 satisfies it. Use native Ollama `http://127.0.0.1:11434` and `api: ollama`, without `/v1`: https://docs.openclaw.ai/providers/ollama/configuration

Ollama lists RTX 3090 (compute capability 8.6) and driver 550+ support: https://docs.ollama.com/gpu . Debian's 550 package is a compatibility candidate, not proof of GPU execution. Acceptance requires live Linux `nvidia-smi`, loaded model GPU allocation in `ollama ps`, runtime logs, and an actual OpenClaw response.

Secure Boot is enabled on Toronado. Signed Debian bootloader/kernel support does not automatically authorize an image-built DKMS NVIDIA module. A trust/enrollment workflow must be verified; do not change firmware settings or Windows boot configuration automatically. CPU VM testing does not validate this.

Repeatable build scripts and fixed dependency inputs do not yet establish byte-identical reproducibility. Two clean rebuilds and digest comparison are required before claiming that property. The builder itself must be pinned by manifest/snapshot before release.
