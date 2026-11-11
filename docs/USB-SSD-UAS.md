# Samsung SSD enclosure: boot on usb-storage, not UAS

The Argos SSD sits in a Realtek RTL9201 USB enclosure (`0bda:9201`). On 2026-11-11 it failed
the same way on three consecutive boots of the fixed-USB image, about 30 to 110 seconds after
the kernel started, while the desktop and Argos were reading from it:

1. `uas_eh_abort_handler` fires for the roughly 30 commands in flight.
2. The UAS reset reports success, a second reset fails (`can't restore configuration #1
   (error=-110)`, `uas_eh_device_reset_handler FAILED err -19`).
3. The device disconnects (`usb 6-4: USB disconnect`), the encrypted ext4 aborts its journal and
   remounts read-only, SQUASHFS reads return `-5`, and `sshd-session` can no longer be started, so
   SSH resets before the banner and the dashboard reports "Startup needs attention".

The image, the SSH policy and the encryption header were not at fault. The failure also left the
persistence filesystem with corrupted group descriptors each time.

## The fix

The kernel parameter `usb-storage.quirks=0bda:9201:u` makes Linux bind that one device to plain
`usb-storage` (the `u` flag ignores UAS). The boot menu generator
(`live/config/hooks/live/050-argos-menu.hook.binary`) adds it to every entry, GRUB and BIOS, and
`scripts/build.sh` and `scripts/repack-image.sh` carry it as well. Other devices are not affected.

With it, a normal boot on the real SSD stayed up and Argos reached the gateway with a verified
model reply. The model load ran at about 280 MB/s and I/O pressure peaked near 31%, where the
failing boots reached 97%.

## Checking it

On a running system:

```sh
grep -F 'usb-storage.quirks=0bda:9201:u' /proc/cmdline
dmesg | grep -E 'UAS is ignored|Quirks match'
```

Expected: `usb-storage.quirks=0bda:9201:u`, `usb 6-4: UAS is ignored for this device, using
usb-storage instead` and `usb-storage 6-4:1.0: Quirks match for vid 0bda pid 9201: 800000`.
`scripts/test-usb-vm.py` checks `/proc/cmdline` for the parameter on every image boot test.

The parameter is easy to mistype. Leaving off the leading `usb-` is silently ignored by the kernel
(the text is only listed under "Unknown kernel command line parameters"), so
`tests/test_ssd_uas_quirk.py` pins the exact spelling everywhere the repository sets it.

## Testing a change safely on hardware

Use the boot menu entry "Argos guest - resets on reboot, no passphrase". It uses
`nopersistence`, so it never unlocks or writes the encrypted filesystem; a stall there cannot
corrupt anything. SSH is not available in guest mode (there is no persisted host identity), so read
the evidence locally with `dmesg`.

## Existing installs

An SSD installed from an earlier image does not have the parameter. Rebuild from this change, or
patch the menu text on the SSD's ISO area in place. That patch is a boot-area write and needs
the same approval and rehearsal as any other SSD write.

## If a stall already happened

The persistence filesystem may refuse to mount (`group descriptors corrupted`) and a plain
`e2fsck -fn` can spin. Repair it from the backup superblock, first against a RAM-only snapshot of
the read-only mapping, and only repair the real device if that comes out clean:

```sh
e2fsck -f -y -b 32768 -B 4096 /dev/mapper/<snapshot>
```

Back up records before powering the machine off whenever SSH still works.
