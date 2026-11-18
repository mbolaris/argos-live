# USB SSDs: find encrypted persistence on disks that report removable=0

Toronado boots from a Samsung SSD in a Realtek RTL9201 USB enclosure. The enclosure reports
`removable=0` in sysfs, like most USB SSDs and many USB hard disks.

## The problem

The image boots with `persistence-media=removable-usb`, so that internal disks are never used for
persistence. Debian live-boot implements this in `removable_dev()` in
`/usr/lib/live/boot/9990-misc-helpers.sh`. In USB mode it keeps a device only if both are true:

1. sysfs `removable` is `1`, and
2. the device has a USB ancestor.

A USB SSD fails the first test. A stock image therefore boots it without persistence: root on RAM,
no paired SSH and no owner records. It does not report an error.

## The fix

`live/config/hooks/live/005-fixed-usb-persistence.hook.chroot` runs
`patch-live-boot-usb.py` in the image chroot. It changes one condition, so that in USB mode the
removable flag is no longer required:

```sh
if [ "$(cat ${sysblock}/removable)" = "1" ] || [ -n "${want_usb}" ]
```

The USB ancestry check stays, so internal NVMe and SATA disks are still never candidates. The
ordinary mode without the USB requirement is unchanged. The hook sorts before
`010-argos.hook.chroot`, which regenerates the initramfs, so the edited helper is what ends up in
`/live/initrd.img`.

The patcher refuses any `removable_dev()` that differs from the reviewed version. A new live-boot
release therefore fails the build instead of silently losing the fix.

## How it is checked

| Check | Where | What it shows |
| --- | --- | --- |
| `tests/test_fixed_usb_persistence.py` | every PR | The edit is exact and idempotent, refuses an unreviewed live-boot, and runs before the initramfs is regenerated. On Linux it also runs the real shell function on mock sysfs: the stock function skips a fixed USB disk and the edited one accepts it. |
| `scripts/check-iso-usb-persistence.py` | every image build (`iso-build.yml`) | Unpacks the built ISO's own initrd, finds the edited helper, and runs it on mock sysfs. The receipt is uploaded as `usb-persistence.json` next to the ISO. |
| `scripts/smoke-encrypted-shutdown.py --fixed-usb` | `iso-boot.yml` with `shutdown_only` and `fixed_usb` | Boots the exact ISO three times from an encrypted virtual USB disk attached with `removable=off`. Each boot must unlock, write records, shut down cleanly and pass read-only fsck. A login prompt before the unlock prompt fails at once. |
| `scripts/repack-image.sh` | repacks | Refuses a configured rootfs that lacks the edit. |

None of these is a physical boot. Before an image is promoted, the first Toronado boot must still
show the encrypted overlay as root and a working paired SSH.

## History

From October 23 to November 15, 2026, each SSD image had this edit applied by hand to the CI ISO's
initrd (`work/ssd-boot-20261023`, `work/toronado-fixed-43734658440`). Every image deployed to
Toronado was therefore a local variant whose bytes were not the CI artifact. Images built with this
change need no initrd edit.

The MBR entry for the persistence partition is still added when the write to a specific disk is prepared,
because its offsets depend on the target disk. The fix for the separate UAS stall on this enclosure
is in [USB-SSD-UAS.md](USB-SSD-UAS.md).
