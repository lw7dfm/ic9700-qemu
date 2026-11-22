# Installation and dependencies

## Requirements

The dependency baseline is Ubuntu 24.04 or a compatible Linux x86-64 system:

- glibc >= 2.38; do not replace the system libc to run this project.
- Python >= 3.10 with Tkinter and venv; an X display, XWayland, or WSLg.
- Git, C/C++ toolchain, Make, pkg-config, and Ninja.
- GLib, Pixman, and zlib development headers.

There are no third-party pip runtime requirements. QEMU's configure step may
obtain its own Python build tools and subprojects online. Native Windows/macOS
and ARM hosts are not supported by the current launcher.

## Normal installation

1. Follow `firmware/README.md`; supply one original or modified compatible DAT.
   A modified input does not need an additional original file.
2. Run `bash INSTALL.sh --install-deps` to review and confirm apt installation.
   It can ask for sudo credentials in the terminal. No credentials are stored.
   This step changes system packages only with explicit confirmation.
3. The installer clones QEMU tag `v11.1.1`, checks commit
   `c3d48b7d1e89604920e5b81b91140c2ad39a1943`, applies the included integration
   patch, and builds the frozen machine models. It does not use a distribution
   QEMU binary, since that binary does not contain this machine.
4. It invokes `START.sh` for preparation and GUI startup.

Manual dependency installation on Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install build-essential git pkg-config ninja-build python3 \
  python3-venv python3-tk libglib2.0-dev libpixman-1-dev zlib1g-dev
bash INSTALL.sh
```

If prerequisites already exist, `bash INSTALL.sh` performs no apt installation.
Use `JOBS=2 bash INSTALL.sh` to reduce build concurrency/memory use.

## Local header extraction (Ubuntu 24.04/noble-based x86-64 only)

For a machine with existing compiler/runtime libraries but missing development
headers, an optional non-system method is provided:

```bash
bash scripts/prepare_deps.sh
bash INSTALL.sh
```

This downloads and extracts Ubuntu development packages (including zlib headers) into `tools/` without
sudo or package installation. It relies on matching host runtime libraries;
it is not a portable sysroot or a substitute for a compatible Linux install.
Do not copy generated tools or sysroot directories to another host; regenerate
them against that host's libraries.

## Paths containing spaces

A source directory may contain spaces. QEMU's configure/venv
cannot reliably build in such paths. The wrapper automatically creates a
private, owned `/tmp/ic9700-lw7dfm-build-<uid>-<path-hash>/` workspace, copies the
same model sources there and installs the resulting binary back under
`qemu-machine/qemu-src/build/`. No QEMU core source is changed to bypass this
limitation. Runtime uses files in the release folder, not that workspace.
The workspace is a reproducible build cache; `/tmp` cleanup may require a rebuild.
A relocated source checkout can be rebuilt by running `INSTALL.sh` again.

## WSL

Use WSL2 with WSLg or a configured X server. Keep the checkout in the Linux home
filesystem. This is not a Windows `.exe`. WSL operation is an intended usage,
not a separately completed platform qualification. `bash START.sh --check`
checks Tk/display and QEMU execution, not radio functionality.

## No network exposure by default

The integrated launcher uses temporary local UNIX QMP sockets and disables VNC.
The optional `run_vnc.py` helper binds VNC to 127.0.0.1 only; it is an advanced
helper requiring prepared asset paths, not the normal startup command. Never
expose unauthenticated QMP/VNC to a network.
