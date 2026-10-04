# Model storage fixtures

Authored Linux mountinfo and lsblk inventories, not Toronado measurements. They represent a USB live medium and persistence partition, two eligible internal filesystems, and an existing tmpfs. Device names and UUIDs are fictional reference data. Tests inject capacity/access results and never mount or write these paths.

Format references: [kernel mountinfo documentation](https://docs.kernel.org/filesystems/proc.html) and [util-linux lsblk manual](https://man7.org/linux/man-pages/man8/lsblk.8.html).
