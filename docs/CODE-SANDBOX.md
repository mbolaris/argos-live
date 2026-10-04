# Code sandbox foundation

B4b1 adds an internal Linux amd64 execution primitive. Ability suites still omit
generated code; coding fixtures and runner integration remain B4b2/B5b.

`code_sandbox.run(source)` executes only through bubblewrap. Unsupported platforms,
missing binaries or failed namespace setup never fall back to a normal subprocess.
`available()` runs a trusted marker probe; callers must treat false as unavailable.
The implementation uses the system Python, isolated mode and no site packages.

The sandbox has separate user, PID, network, IPC, UTS and cgroup namespaces, drops
all capabilities, clears environment variables and remounts its root read-only.
Only the system Python executable and library directories are mounted read-only.
No home, `/etc`, `/run`, `/proc`, host sockets or devices are exposed. `/work` is a
fresh 16 MiB tmpfs; source arrives through an anonymous memory descriptor. There
is no writable host mount or persisted code file. Bubblewrap behavior follows the
[Debian manual](https://manpages.debian.org/trixie/bubblewrap/bwrap.1.en.html).

A native amd64 seccomp filter rejects other architectures/x32 calls and denies
network socket creation/connections, forks/clones, namespace/mount changes,
keyring access, process tracing/memory access and selected kernel interfaces.
Numbers are checked against the [Linux amd64 syscall table](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/syscalls/syscall_64.tbl).
This filter is inherited across exec. The policy assumes a maintained Linux
kernel and trusted system Python/libraries; it is not a general hostile-code
hosting service or a guarantee against kernel vulnerabilities.

The trusted launcher applies hard CPU, memory, file-size, descriptor and core-dump
limits before exec. Process creation is denied by seccomp after bubblewrap setup;
a per-user process-count limit would also count unrelated host workloads. Wall
timeout, cancellation and output overflow kill the launcher process group. PID
namespace cleanup and parent-death handling remove the sandbox. Output is bounded
to 8 KiB per stream; source to 64 KiB. Results distinguish completion, error,
timeout, cancellation and output limit.

Actual Linux CI tests filesystem rejection and temporary cleanup, environment
isolation, network/process/x32/kernel denials, wall timeout, cancellation, output
and memory bounds, and wrong/malformed code. Its launcher runs as root to avoid
Ubuntu's host-specific unprivileged namespace policy; sandbox capabilities are
still dropped. This proves those tested boundaries, not unprivileged Debian Live
availability. That probe and code-category activation remain required before
claiming full B4/B5 acceptance. No host security policy is disabled.
