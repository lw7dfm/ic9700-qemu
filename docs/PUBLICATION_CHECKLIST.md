# Source release checklist

Before making a source release:

- Run the regression suites and the source-distribution audit.
- Review copyright notices, third-party license exceptions, and upstream versions.
- Regenerate the source manifest after any intentional source change.
- Exclude user DATs, decoded components, virtual flash, EEPROM, calibration,
  native UI screenshots, logs, build trees, credentials, and repository history.
- Keep only instructions in `firmware/`; do not force-add ignored firmware data.
- Check links, setup commands, supported platforms, and documented limitations.
- Extract the ZIP into a clean directory and repeat the audit and source tests.
- Verify the archive checksum before sharing it.

The privacy audit uses generic heuristics. It complements manual review; it does
not guarantee that every possible sensitive reference or licensing issue has
been found. Loopback addresses, standard system paths, public upstream links,
and required copyright attributions are intentional.
