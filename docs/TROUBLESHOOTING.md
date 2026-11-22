# Troubleshooting

- **Selecting firmware:** supply one original or modified v1.50-compatible DAT,
  not a renamed ZIP or raw flash dump. No second original DAT is needed.
- **Stock hash failure:** stock mode requires the exact official baseline. For
  a deliberately modified DAT, use auto/experimental mode instead of removing
  validation guards. Experimental mode still rejects bad container MD5, wrong
  geometry, truncated streams and mismatched explicit fingerprints.
- **QEMU not found:** run `bash INSTALL.sh --build-only`. A normal system QEMU
  does not contain the custom machine.
- **Build failure:** inspect the terminal output; check compiler, GLib/Pixman
  headers and Internet access. Retry with fewer `JOBS`. Do not copy the
  developer's compiled libraries or replace glibc.
- **No display / Tk error:** run in a graphical desktop or WSLg session with a
  working DISPLAY/WAYLAND configuration. A headless SSH session alone is not a
  graphical display.
- **First preparation waits:** ARM seed generation and a second cold boot can
  each take up to three minutes plus startup/shutdown. Inspect `work/processed/`
  partial-generation diagnostics. Failure must not be bypassed.
- **Profile busy:** another instance holds the same profile lock. Close it
  cleanly or choose another `--state-name`; do not delete an active lock file.
- **Settings not saved:** allow the guest's periodic save to finish, then close
  the integrated app normally. Force killing can lose the current session.
- **DV DSP/FPGA version warning:** synthetic compatibility peers are partial; a
  queued warning may appear during boot. Dismiss its Close button through the
  normal LCD touch interface. Do not change firmware hash gates or guest flags;
  this is not a prompt to update a real transceiver.
- **A menu or peripheral does not behave like hardware:** the model is partial.
  Report the operating-system version, source manifest, steps and relevant text
  logs. Remove personal
  paths/device data. Do not attach Icom DATs, decoded images, EEPROM, native UI
  screenshots or dumps to public issue reports without appropriate rights.

Reprocessing preserves existing profiles; it is not a factory reset. Use a new
profile name for a fresh synthetic configuration.
