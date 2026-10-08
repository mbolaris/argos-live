# Fresh media and guest sessions

The default boot entry is **Argos desktop**, which restores encrypted persistence
when present and asks for its passphrase. To start fresh without unlocking saved
data, explicitly select **Argos guest - resets on reboot, no passphrase**.
It uses Debian Live `nopersistence` and `argos.guest=1`, without encrypted
persistence boot arguments. An existing encrypted partition is not unlocked
or loaded by this entry. A basic-graphics guest entry is also available.

Guest sessions start from the image defaults, including the bundled Qwen3
0.6B model, conversation-only permissions, and a new local gateway token.
Profiles, conversations, settings, trials and downloaded models use RAM.
Argos refuses disk model stores and persistence-retention checks in guest
mode. Automatic setup checks RAM backing before writing its workspace.
The dashboard and welcome window label the session as temporary.

Rebooting discards that workspace. This is not a sandbox or secure erasure:
explicitly saving a file outside Argos to an attached drive can retain it.
Guest mode does not encrypt RAM or prevent all operating-system disk access.
It does not claim that any private persistence was tested or recovered.

**Argos desktop** and the original basic-graphics and diagnostics entries
remain available for an existing encrypted personal installation. They keep
their persistence/unlock arguments. Switching to guest leaves that personal
partition untouched, but its profile and SSH configuration are unavailable.

## Creating a new default drive

Write a fully verified hybrid ISO to a separately identified, expendable USB
drive or SD card in a USB reader. This erases that selected medium. A fresh
guest-only drive needs no persistence partition or passphrase. Space beyond
the image is unused; large downloads are bounded by available RAM in guest
mode. Persistent personal storage is a separate provisioning step.

Do not clone a personal drive or include its profiles, keys, histories or
storage selections. Do not reuse an old physical-device number as identity.
Verify the complete written ISO region against its SHA256 before ejecting.
Reader firmware boot support requires a physical boot test.

## Acceptance scope

`smoke-qemu-iso.py ISO --output OUTPUT --setup-mode managed --guest` boots
the shipped guest entry, verifies RAM backing for Argos data locations, no
mounted persistence, and the existing managed startup/Model Lab checks.
Inspect the actual shipped Firefox capture. The result separately states that
reboot reset, browser-submitted reply, firmware boot and physical acceptance
are not established by that single direct-kernel run. Test reboot reset with
a disposable marker in a guest workspace and a second fresh guest boot.
