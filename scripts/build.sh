#!/usr/bin/env bash
# Frozen model sources, unmodified QEMU core, locally generated build workspace.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/qemu-machine/qemu-src"
COMMIT=c3d48b7d1e89604920e5b81b91140c2ad39a1943
if [[ ! -d "$SRC/.git" ]]; then
  git clone --depth 1 --branch v11.1.1 https://gitlab.com/qemu-project/qemu.git "$SRC"
fi
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$COMMIT" ]] || { echo 'Unexpected QEMU revision; refusing to build.' >&2; exit 1; }
# QEMU configure/venv do not support spaces. Build in an automatically generated
# private workspace, then install the binary inside this folder. No development
# tree, prebuilt binary or external project file is required.
KEY="$(printf '%s' "$ROOT" | sha256sum | cut -c1-16)"
CACHE="/tmp/ic9700-lw7dfm-build-${UID}-${KEY}"
if [[ ! -e "$CACHE" ]]; then mkdir -m 700 "$CACHE"; fi
[[ -d "$CACHE" && ! -L "$CACHE" && -O "$CACHE" ]] || { echo 'Unsafe build workspace.' >&2; exit 1; }
BUILD_SRC="$CACHE/qemu"
if [[ ! -d "$BUILD_SRC/.git" ]]; then git clone --no-hardlinks "$SRC" "$BUILD_SRC"; fi
[[ "$(git -C "$BUILD_SRC" rev-parse HEAD)" == "$COMMIT" ]] || exit 1
if ! git -C "$BUILD_SRC" apply --reverse --check "$ROOT/qemu-machine/patches/hw-arm-build.patch" 2>/dev/null; then
  git -C "$BUILD_SRC" apply "$ROOT/qemu-machine/patches/hw-arm-build.patch"
fi
for f in "$ROOT"/qemu-machine/src/*.[ch]; do cp "$f" "$BUILD_SRC/hw/arm/$(basename "$f")"; done
if [[ -d "$ROOT/tools/sysroot/usr/lib/x86_64-linux-gnu/pkgconfig" ]]; then
  # pkg-config's prefix must also avoid spaces for configure's shell tests.
  mkdir -p "$CACHE/sysroot"
  cp -a "$ROOT/tools/sysroot/." "$CACHE/sysroot/"
  python3 - "$CACHE/sysroot" "$ROOT/tools/sysroot" <<'PY'
from pathlib import Path
import sys
for p in Path(sys.argv[1]).rglob('*.pc'):
    s=p.read_text().replace(sys.argv[2],sys.argv[1]);p.write_text(s)
PY
  export PKG_CONFIG_PATH="$CACHE/sysroot/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi
mkdir -p "$BUILD_SRC/build"
cd "$BUILD_SRC/build"
if [[ ! -f build.ninja ]]; then
  ../configure --target-list=arm-softmmu --disable-docs --disable-werror --disable-gtk --enable-vnc --disable-tools
fi
ninja -j"${JOBS:-4}" qemu-system-arm
mkdir -p "$SRC/build"
cp qemu-system-arm "$SRC/build/qemu-system-arm.new"
chmod 755 "$SRC/build/qemu-system-arm.new"
mv "$SRC/build/qemu-system-arm.new" "$SRC/build/qemu-system-arm"
"$SRC/build/qemu-system-arm" --version
printf 'Build workspace: %s\n' "$CACHE"
