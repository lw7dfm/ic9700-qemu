# One selected DAT, original or modified

The firmware under test is the only firmware input. **No additional official DAT,
stock-produced EEPROM seed or stock cache is required for a modified DAT.**

```bash
bash START.sh
# Select an original or modified DAT once.

bash START.sh --firmware /path/to/selected.dat
# Auto-classifies exact known stock; otherwise requests experimental consent.

bash START.sh --mode experimental --firmware /path/to/modified.dat
# Explicit experimental mode, still one input.
```

For a repeatable automated selection, pin consent to the exact input bytes:

```bash
sha256sum /path/to/modified.dat
bash START.sh --mode experimental --firmware /path/to/modified.dat \
  --expected-sha256 YOUR_64_HEX_SHA256 --accept-experimental --prepare-only
# After preparation:
bash START.sh --mode experimental --firmware /path/to/modified.dat \
  --expected-sha256 YOUR_64_HEX_SHA256 --accept-experimental --choice run
```

Tk/display is still needed. Explicit missing paths, wrong fingerprints, malformed
geometry, bad MD5 or truncated/unreasonably sized streams fail; no second file is
silently substituted. Known official stock can be requested explicitly with
`--mode stock`, retaining exact independent code/data hash pins.

## What is generated from the selected firmware

1. The selected DAT's bootstrap/main/graphics domain is decoded and mapped to
   virtual flash. The original input is never edited.
2. `firmware_environment.py` checks the supported v1.50 ROM-pointer/template
   layout inside that **same decoded main** and builds a synthetic auxiliary
   EEPROM input from it. Out-of-range pointers fail transparently.
3. Fixed compatibility peer settings belong to the partial machine model; they
   are not another firmware. No original/stock DAT or prebuilt seed is loaded.
4. The selected ARM runs against that synthetic input and writes its own defaults.
   The host observes initialization/journal completion and a stable backing file.
   It does not require stock tuning frequencies, a stock main hash or software
   TX-clear bits for an experiment. Actual observations remain in diagnostics.
5. A separate cold readback observes that candidate's saved settings without
   resetting/replacing them. Only then is the generation atomically published.

If preparation fails, diagnostics are preserved and the previous generation is
not replaced. There is no fallback to stock, forced guest return, guest RAM/PC
patch or automatic repair of candidate behavior. A successful settings-preparation
check is **not** full firmware or hardware validation.

## Scope

IC-9700 v1.50-compatible container geometry is currently supported: model tag,
0x38 main-domain offset, 8 MiB encoded domain, matching domain MD5 and bounded
LZSS streams. Decoded main is limited to 8 MiB, graphics to 16 MiB. Templates must
remain compatible with the modeled ROM-pointer layout. This does not promise
that every modified DAT or substantially different release will boot.

Only bootstrap/main/graphics execute. Container metadata and external FRONT/
sub-CPU/DSP/FPGA payloads are not executed. Their presence is recorded; their
behavior cannot be validated with this main-CPU model. No full physical update,
power-cut/dual-bank recovery, RF/PTT or board-equivalence claim is made.

## Cache and profiles

Candidate caches are fingerprinted under `work/experiments/<SHA256>/`. Required
outputs include the selected main, its own raw synthetic input, guest-created
seed and both preparation/readback diagnostics; all have recorded hashes.

Experimental profiles are bound to the full DAT fingerprint and the synthetic-
environment version. Incompatible cache versions are regenerated, and profiles from a different
environment are not silently adopted. Existing data is not deleted. Reprocessing
preserves profiles within the same environment; use `--state-name short-label`
for another fresh profile.

Firmware is code. QEMU is not a promise of containment against malicious inputs;
use an appropriate disposable environment for untrusted firmware.

Some internal filenames retain historical labels such as `ic9700-flash-stock.bin`
and `panel-stock-flags.bin`. In an experimental generation these are outputs
created for the selected DAT, not files read from another stock installation.
The input/main/flash/seed hashes and provenance are recorded in PREPARED.json.
