# Contributing

Keep changes reproducible and separate source code from user-owned firmware.
Do not submit DATs, dumps, decoded images, EEPROM, calibration, or personal logs.
Preserve existing copyright notices and file-specific license terms.

Run all three source regression suites and the clean-release audit described in
`docs/TESTING.md`. With a graphical display and one authorized DAT,
`tests/gui_integration.py` can check stock or experimental firmware; see its
`--help` for the input and expected-hash options. It writes ignored local
screenshots and is not an RF test.

Keep strict stock hash gates. Use the explicit experimental importer for modified
DATs and add bounds/negative tests instead of disabling integrity checks. Model
changes need guest-observed evidence and clear limits.

For a bug report, describe the operating system, relevant tool versions, pinned
QEMU revision, model inputs, and reproduction steps. Redact personal paths and
identifiers. Avoid unsupported claims of full hardware emulation, transmitter
safety, or physical installation/recovery certification.
