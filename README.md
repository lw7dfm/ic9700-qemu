# IC-9700 QEMU Emulator — LW7DFM

I'm LW7DFM, and this is my IC-9700 adaptation of
[Jeskko's IC-7300 emulator](https://github.com/jeskko/ic7300-homebrew).
I built it to explore how the IC-9700 firmware behaves and to test changes on
my computer before considering anything on a real radio.

The idea is simple: **choose one DAT file, original or modified, and run that
firmware in QEMU**. A modified image does not need a second copy of the original
firmware, a stock settings file, or a previously prepared stock installation.

Jarkko Vääräniemi (Jeskko) deserves clear credit for the original IC-7300 work
that made this adaptation possible. My work here is the IC-9700 adaptation,
its peripheral integration, firmware-loading workflow, and desktop controls.
QEMU and the other third-party components keep their own credits and licenses;
I've listed them in [NOTICE](NOTICE).

## Screenshots

Here are two captures of the emulator running original IC-9700 v1.50 firmware
on a Linux desktop. They show the firmware's native interface.

### Main display and emulator controls

![IC-9700 main display and emulator controls](https://github.com/lw7dfm/ic9700-qemu/releases/download/v1.0.0/ic9700-main-panel.png)

### Native main menu

![IC-9700 native main menu](https://github.com/lw7dfm/ic9700-qemu/releases/download/v1.0.0/ic9700-menu.png)

I've cropped the application view to its LCD and controls, without changing the
LCD content. These captures illustrate the interface, not RF operation. The
Icom interface shown is not covered by my MIT license; see
[NOTICE](NOTICE).

## What it does

The emulator runs the selected DAT's bootstrap and main ARM application, and
displays the firmware's own 480 × 272 LCD in a Tkinter window. You can use the
touchscreen, main tuning dial, power input, and five navigation keys.

The selected firmware supplies the templates for a synthetic settings device,
then its own ARM code creates the defaults. Settings are kept in separate
profiles, so a modified firmware does not silently reuse the original's profile.
The launcher checks file integrity, caches prepared images, and saves settings
after a clean shutdown.

**I don't include Icom firmware in this repository.** You'll need to supply a
DAT file you are entitled to use. The emulator does not connect to a radio,
receive signals, or generate RF.

## Getting started

I target **Linux x86-64**, with Ubuntu 24.04 or a compatible environment as the
build-dependency baseline. You'll need glibc 2.38 or newer, Python with Tkinter,
and a working graphical display. WSL2 needs WSLg or a configured X server.
I haven't independently qualified WSL or other host platforms, so please treat
those as platforms to test rather than a compatibility guarantee.

Allow several GB of disk space for the QEMU checkout and build. The installer
needs Internet access for QEMU and its build tools; it never downloads firmware.
There are no third-party pip runtime packages to install.

1. Extract this project into a writable directory in your Linux filesystem.
2. Have your **one IC-9700 v1.50-compatible DAT** ready. For the official release,
   download it from [Icom](https://www.icomjapan.com/support/firmware_driver/4424/),
   review their terms, and extract `9700E150.dat`. A compatible modified DAT can
   be selected directly instead.
3. Open a terminal in the project directory and run:

   ```bash
   bash INSTALL.sh --install-deps
   ```

   Review and confirm the dependency installation. The script builds the pinned
   QEMU source, then asks you to select your DAT. The first build and settings
   preparation may take a few minutes.
4. For later runs:

   ```bash
   bash START.sh
   ```

   You can also give it the file directly:

   ```bash
   bash START.sh --firmware "/path/to/selected.dat"
   ```

You may keep the DAT in `firmware/` or select it from somewhere else. The input
is never edited, and the emulator does not create an installable update file.
See [installation details](docs/INSTALLATION.md) for dependencies, build options,
and WSL notes.

## Original and modified firmware

The default mode recognizes the known official v1.50 input by its SHA-256:

```text
001f34f2263bddebbf4a277d675918f1d68bef4c96537461d1fc495745ba8bb5
```

Other supported inputs ask for confirmation as experiments. They still need
valid container geometry, MD5, and bounded compressed streams, but they don't
have to match a particular modified-firmware hash.

For explicit mode selection:

```bash
bash START.sh --mode stock --firmware /path/to/official.dat
bash START.sh --mode experimental --firmware /path/to/modified.dat
```

I've documented the format limits, reproducible command-line options, and profile
handling in [Firmware loading](docs/EXPERIMENTAL_FIRMWARE.md).

## Controls and settings

| Control | Action |
| --- | --- |
| Click the LCD | Touchscreen press and release |
| Scroll over the LCD, or Dial − / Dial + | Main tuning dial |
| Power (pulse) | Front-panel power input |
| MENU, FUNCTION, M.SCOPE, QUICK, EXIT | Native navigation keys |

There is no host PTT/TX button. Firmware language and menu behavior come from
the guest; the English host interface does not translate the radio's menus.

Close the integrated application normally to stop QEMU and save its synthetic
settings. Give the guest a few seconds to finish a periodic save after making
changes. A separately launched control panel only disconnects when closed.
Force-killing a session can lose recent settings.

Generated files stay under `work/`, which is excluded from the source release.
Modified firmware gets an environment-versioned, fingerprint-bound profile;
`--state-name short-label` lets you use another isolated profile. These files
are synthetic settings, not backups or calibration for a physical radio.

## Where the model stops

This is a useful firmware workbench, not a complete IC-9700 in software.

- The bootstrap, main ARM application, and graphics run. External FRONT,
  sub-CPU, DSP, and FPGA firmware payloads do **not** run; their peers are partial
  synthetic models.
- RF, real signal processing, audio-chain fidelity, physical PTT, and transmitter
  safety are outside what I can validate with this emulator.
- The firmware importer supports the modeled v1.50 container and ROM-template
  layout. A substantially different layout or unmodeled hardware requirement
  may prevent preparation or boot.
- Settings preparation observes initialization and saving; it does not force the
  guest to pass. Failures leave diagnostics rather than falling back to another
  firmware or patching guest RAM/PC.
- A queued DV/FPGA compatibility warning may need closing through the normal
  touchscreen dialog.

A successful emulator test is not proof that firmware is safe to install or use
on a real radio. See [Architecture](docs/ARCHITECTURE.md),
[Testing](docs/TESTING.md), and [Troubleshooting](docs/TROUBLESHOOTING.md).

## Building on the project

The machine sources are in `qemu-machine/src/`; the QEMU integration patch is in
`qemu-machine/patches/`. The launcher, panel, importers, and settings support live
in `scripts/`. QEMU is fetched and built locally rather than shipped as a binary.

```bash
python3 -B scripts/test_control_panel.py
python3 -B scripts/test_seed_validation.py
python3 -B scripts/test_experimental_firmware.py
```

For contributions, please keep firmware and generated data out of patches and
issue attachments, retain the existing license notices, and describe both your
test results and the model's limits. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License and acknowledgements

My project-owned work and the MIT-derived components use the [MIT license](LICENSE).
Some model files and the QEMU integration have GPL terms; the combined QEMU
executable is not blanket MIT licensed. The applicable exceptions, upstream
credits, decoder attribution, and dependency notices are in [NOTICE](NOTICE)
and `LICENSES/`.

Icom and IC-9700 are trademarks of Icom Inc. This is an independent amateur-radio
project, not affiliated with or endorsed by Icom. Please respect the firmware's
terms and applicable law.
