# Optional internal model and data storage

Argos can boot from an encrypted-persistence USB while storing large local model files and other files on an existing writable data volume. This is optional and specific to each computer. Never bake a machine's disk UUID, Windows drive letter, disk number, or private credentials into the image.

Identify the current volume and filesystem before enabling writes. Use a dedicated folder, not Windows system directories. A clean, unencrypted NTFS data volume can be mounted with ntfs-3g; honor hibernation or unclean-volume refusals. Never force a mount, discard a Windows hibernation file, unlock BitLocker, or change partitions as part of this workflow. FAT/exFAT/NTFS data remains unencrypted unless separately protected.

Use a stable filesystem UUID for optional persistent mounting, with nofail and an automount device timeout so a missing drive does not block the desktop. Appropriate options include the desktop user's uid/gid, restrictive permissions, nodev, nosuid, and noexec. Derive identity and user IDs from the current machine; do not copy another machine's fstab entry.

First setup can select an existing mounted model folder using the welcome window. To migrate configured models, stop the assistant at a convenient point, copy the model folder and storage-identity marker, verify every referenced model blob with SHA256, back up the private state, and update its selected path only after verification. Retain the original copy until a successful restart and reboot test. Argos refuses missing, unwritable, or differently identified model storage rather than creating fallback model folders.

Keep conversations, OpenClaw configuration, and authentication tokens on encrypted USB persistence unless the owner explicitly chooses another protected location. A model directory on an internal data volume does not move those settings automatically. An already-running model daemon retains its original storage path until restarted.
# Persistent image updates

Argos Live keeps the owner’s encrypted persistence overlay when the boot image
is refreshed. That overlay can retain an older copy of a distro-owned command
and make it take precedence over the newer file in the image. Before the
desktop starts, `argos-refresh-runtime.service` compares the three Argos
entrypoint scripts with the immutable image and atomically refreshes only those
scripts when they differ. It does not touch the owner’s home directory, model
storage, OpenClaw configuration, or other persistence data. On non-live or
unverified root filesystems it makes no changes.
