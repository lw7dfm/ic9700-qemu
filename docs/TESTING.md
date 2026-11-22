# Testing

## Source regressions

Run these from the project root; no firmware or graphical display is needed:

```bash
python3 -B scripts/test_control_panel.py
python3 -B scripts/test_seed_validation.py
python3 -B scripts/test_experimental_firmware.py
```

There are 40 tests: 8 for QMP/panel behavior, 6 for strict stock readiness, and
26 for parsing, bounds, environment construction, profile isolation, and cache
handling. Modified-firmware preparation does not require stock tuning defaults
or clear software TX flags. It observes initialization and settings-save activity
without patching guest RAM/PC or forcing a return.

For a clean source distribution, also run:

```bash
python3 -B tests/audit_release.py
```

This checks the source manifest and common accidental leaks. It deliberately
rejects firmware, generated trees, archives, and key material; run it before
installation or against a clean source copy, not a populated working directory.
It is a heuristic check, not a substitute for manual review.

## Runtime checks

With a graphical display and a DAT you are entitled to use:

```bash
bash START.sh --check
bash START.sh --firmware /path/to/selected.dat
```

Confirm the native LCD appears, navigation works, and settings survive a clean
close and a new launch. A compatible modified DAT should work without another
stock file, stock seed, or stock cache.

`tests/gui_integration.py` provides a longer automated check. It accepts a mode,
DAT path, and expected main hash; see `--help`. It observes the full selected
main in guest RAM, exercises MENU/EXIT and ten dial detents, then closes normally.
Firmware and screenshots produced by runtime tests are never source-release
contents. The short launcher's `--smoke-test` checks connection/capture/shutdown;
on a slow boot it may still capture the startup logo rather than the main UI.

A single detent can update only an internal tuning remainder; do not assume a
universal Hz-per-detent value. Queued synthetic DV/FPGA warnings may need normal
touchscreen dismissal; the longer test reports these rather than clearing guest
flags. Settings publication is not a guarantee against incomplete guest writes
or power failure.

The functional v3 checks cover original and modified input, guest-created
settings, cold readback, native navigation, and separate profiles. See
`RELEASE_VERIFICATION.json` for the summary. These results do not establish
compatibility for every firmware, complete peripheral emulation, or physical
radio/RF/transmitter safety.
