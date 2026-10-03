# Private Windows configuration export

`scripts/export-personal-config.py SOURCE PRIVATE_DESTINATION` captures the customized Windows `agents.entries` configuration for Argos, Nyx and Proteus as migration reference data. It does not install or activate anything. The source is unchanged.

Create an empty destination with access restricted to the owner and SYSTEM before running the exporter. Keep it outside source control, preferably on encrypted storage. The project `local/` directory is Git-ignored, but its default Windows permissions are insufficient; restrict the export directory explicitly.

The archive contains a redacted configuration snapshot, profile instruction files and top-level memory summaries, Markdown skill definitions, migration notes, and a checksum manifest. Credential stores, conversation sessions, daily history, databases, media, model weights and executable helpers are excluded. Linked skill directories are recorded as excluded references rather than followed into runtime installations.

Known credential values and recognizable secret patterns are removed in memory. Arbitrary free-form notes still require private review before transfer or import. This export is personal information and must never be committed or published.

The Windows source uses a customized schema; it cannot replace the live system configuration directly. Review model identifiers, Windows paths, plugin compatibility, and execution permissions before a deliberate import. Transfer only through an authenticated private channel, such as SSH after verifying the destination host key. No restoration or permission grant occurs automatically.

The exporter verifies archive CRCs and each manifest hash, then writes `SHA256SUMS`. Private restoration remains a separate milestone.

To stage this reference ZIP, use `scripts/stage-config-reference.py ARCHIVE --sha256 EXPECTED --target NEW_PRIVATE_DIRECTORY`. This tool verifies the transfer digest, CRCs, exact manifest coverage and every payload hash before extraction. It rejects traversal, links and duplicate names, and refuses an existing destination. Windows output permissions are restricted to the current owner and SYSTEM; Linux output directories/files use modes 700/600. Choose encrypted storage yourself; the tool does not mount or select a volume.

Staging keeps the files inert. It does not invoke OpenClaw, apply source permissions, restore credentials, run helper scripts or copy model weights. The native-backup helper `stage-openclaw-profile.py` handles a different archive format and cannot consume this ZIP.
