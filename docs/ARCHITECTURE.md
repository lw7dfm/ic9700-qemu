# Architecture and source provenance

The emulator runs the original main ARM application on QEMU's ARM TCG engine,
with a custom `rz-a1h` machine. The desktop model represents a partial IC-9700 hardware environment.
The LCD content is produced by the guest, not a host-side reproduction of the
radio's menus. The host panel requests screen images and sends allowlisted
input events through QMP.

## Components

- Machine/memory map, GPIO, interrupt wiring and partial Renesas peripherals.
- OSTM/MTU timers, DMA, SCIF, RIIC, RSPI, SDHI/MMC, SPI flash interface.
- VDC5/OpenVG display path, RTC/ADC and compatibility placeholders.
- Synthetic version/status peers, ideal reference input and coherent synthetic
  auxiliary EEPROM read/write path used by the tested desktop configuration.
- Standard-library Python launcher, QMP client and Tkinter panel.

Not all registers, timing behavior or physical bus arrangements are modeled.
Synthetic peers are explicitly model inputs, not measurements from a radio.
The machine exposes diagnostic environment switches; the normal launcher clears inherited `IC9700_`/`RZA1H_` environment
variables before applying its known desktop configuration.

## Firmware preparation — one input

The launcher selects one DAT. Auto mode recognizes the exact official stock hash;
other compatible inputs require explicit experimental consent. Stock mode keeps
independent official DAT/body/main/graphics/bootstrap/flash pins. Experimental
mode checks geometry, domain MD5 and bounded decoding without a stock DAT.

`firmware_environment.py` derives synthetic ROM templates only from the selected
main, with bounded pointer reads. That firmware generates its own EEPROM defaults.
Preparation observes initialization and journal completion, then cold-readbacks
those saved bytes. Candidate gates impose neither stock frequencies nor stock
software TX-clear bits. This is settings preparation, not RF/safety certification.
No guest RAM/PC writes, forced returns or foreign firmware substitutions occur.
Unsupported template layouts and initialization failures are reported, not hidden.

External component firmware is not executed; version/status peers remain partial
synthetic model inputs. See EXPERIMENTAL_FIRMWARE.md for limits and profile/cache
isolation.

## Settings and shutdown

Each named profile uses an exclusive lock. Four session backing files represent
synthetic EEPROM banks. Only clean QEMU termination publishes the combined
state using atomic replacement and fsync. Unclean exits preserve the previous
canonical state. Periodic guest saves/incomplete transactions can still lose
recent changes; this is not a power-failure guarantee.

## Upstream versions

- Jeskko `ic7300-homebrew` baseline:
  `84fb65b457f00bddcf5fb3d044e9f29dad3be48b`.
- QEMU tag `v11.1.1`, commit:
  `c3d48b7d1e89604920e5b81b91140c2ad39a1943`.
- Decoder copied with the supplied Dawid SQ6EMM MIT notice. Its exact upstream
  revision is not recorded in the imported snapshot. `SOURCE_MANIFEST.json` records the actual shipped bytes.

The build integration selects the model files under `qemu-machine/src/`.
`build.sh` copies all `.c`/`.h` files, including RSPI0 and the reference meter,
into the pinned QEMU checkout. Runtime firmware is supplied separately by the
user and is not part of this source distribution.
