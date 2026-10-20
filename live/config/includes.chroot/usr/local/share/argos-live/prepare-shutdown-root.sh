#!/bin/bash
# Image build and boot staging only. Never run this on an owner machine as a fix.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Shutdown-root preparation requires root.' >&2; exit 1; }
source_tree=/usr/local/share/argos-live/shutdown-root
ram_tree=/run/initramfs
preparer_sha256=$(sha256sum -- "${BASH_SOURCE[0]}" | cut -d ' ' -f1)

case "${1:-}" in
  --build)
    # Keep the pinned distro's shutdown implementation, loader and libraries.
    # Original paths matter: systemd-shared uses an executable-relative RPATH.
    [[ ! -e "$source_tree" ]] || { echo 'Shutdown-root template already exists; review before rebuilding.' >&2; exit 1; }
    mkdir -p "$source_tree"/{usr/bin,usr/sbin,usr/lib,usr/lib64,etc,dev,proc,sys,run,oldroot}
    for name in bin sbin lib lib64; do ln -s "usr/$name" "$source_tree/$name"; done
    export DESTDIR="$source_tree" verbose=n
    # The Debian hook helper is sourced in its native (non-nounset) environment.
    set +u
    . /usr/share/initramfs-tools/hook-functions
    copy_exec /bin/sh
    copy_exec /usr/lib/systemd/systemd-shutdown
    set -u
    printf 'ID=argos-shutdown\nNAME="Argos shutdown RAM environment"\n' > "$source_tree/etc/initrd-release"
    cat > "$source_tree/shutdown" <<'EOF'
#!/bin/sh
set -eu
printf 'ARGOS_EXITRD_ENTERED: handing storage teardown to pinned systemd-shutdown\n' > /dev/console
exec /usr/lib/systemd/systemd-shutdown "$@"
EOF
    chmod 700 "$source_tree/shutdown"
    printf '%s\n' "$preparer_sha256" > "$source_tree/PREPARER_SHA256"
    # Resolve the copied ELF closure without executing a shutdown command.
    # The image architecture is pinned amd64. Also check the wrapper's shell.
    chroot "$source_tree" /lib64/ld-linux-x86-64.so.2 --list /usr/lib/systemd/systemd-shutdown >/dev/null
    chroot "$source_tree" /bin/sh -c ':'
    # No keys, owner configuration, model files or agent workspace are copied.
    (cd "$source_tree"; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
    ;;
  --stage)
    [[ -f "$source_tree/SHA256SUMS" && -x "$source_tree/shutdown" ]] || {
      echo 'Image lacks a complete shutdown-root template.' >&2; exit 1;
    }
    [[ "$(cat "$source_tree/PREPARER_SHA256")" == "$preparer_sha256" ]] || {
      echo 'Shutdown template does not match this preparer; a fresh image build is required.' >&2; exit 1;
    }
    (cd "$source_tree"; sha256sum --strict --quiet -c SHA256SUMS)
    [[ ! -L "$ram_tree" ]] || { echo 'Refusing linked shutdown-root path.' >&2; exit 1; }
    mkdir -p "$ram_tree"
    # Preserve any shutdown environment supplied by another initrd. Do not
    # replace it, and do not assert that it implements the Argos acceptance gate.
    [[ -z "$(find "$ram_tree" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
      echo 'Existing shutdown environment requires review; it was preserved.' >&2; exit 1;
    }
    mountpoint -q "$ram_tree" && { echo 'Existing shutdown-root mount requires review.' >&2; exit 1; }
    # /run on this image is noexec. A distinct executable RAM mount is required.
    mount -t tmpfs -o mode=0700,size=64m,nodev,nosuid,exec argos-shutdown "$ram_tree"
    # Keep a partial failure unexecutable: publish /shutdown only after all
    # dependencies and their checksums have been copied and verified.
    install -m 600 "$source_tree/shutdown" "$ram_tree/shutdown"
    for entry in "$source_tree"/*; do
      [[ "$entry" == "$source_tree/shutdown" ]] || cp -a "$entry" "$ram_tree/"
    done
    (cd "$ram_tree"; sha256sum --strict --quiet -c SHA256SUMS)
    chmod 700 "$ram_tree/shutdown"
    printf 'ARGOS_EXITRD_READY: executable RAM shutdown environment staged\n'
    ;;
  *) echo 'Usage: prepare-shutdown-root.sh --build|--stage' >&2; exit 2 ;;
esac
