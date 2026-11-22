#!/usr/bin/env bash
# Ubuntu24.04 host: downloads/extracts development packages locally; never apt install/sudo.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. /etc/os-release
[[ "${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}" == noble && "$(uname -m)" == x86_64 && ( "${ID:-}" == ubuntu || " ${ID_LIKE:-} " == *' ubuntu '* ) ]] || { echo 'Local header extraction supports Ubuntu 24.04 / noble-based x86-64 systems only; install normal development dependencies instead.' >&2; exit 1; }
mkdir -p "$ROOT/tools/debs" "$ROOT/tools/sysroot"
cd "$ROOT/tools/debs"
apt-get download libglib2.0-dev libpixman-1-dev libffi-dev libpcre2-dev zlib1g-dev
for f in *.deb; do dpkg-deb -x "$f" "$ROOT/tools/sysroot"; done
python3 - "$ROOT" <<'PY'
from pathlib import Path
import sys
r=Path(sys.argv[1])/'tools/sysroot'
for p in r.rglob('*.pc'):
 p.write_text(p.read_text().replace('prefix=/usr','prefix='+str(r/'usr')))
libs={'glib-2.0':'libglib-2.0.so.0','gthread-2.0':'libgthread-2.0.so.0','gmodule-2.0':'libgmodule-2.0.so.0','gobject-2.0':'libgobject-2.0.so.0','gio-2.0':'libgio-2.0.so.0','pixman-1':'libpixman-1.so.0','ffi':'libffi.so.8','pcre2-8':'libpcre2-8.so.0','z':'libz.so.1'}
for lib,target in libs.items():
 system=Path('/usr/lib/x86_64-linux-gnu')/target
 if not system.exists():raise RuntimeError('Missing host runtime library: '+str(system))
 p=r/'usr/lib/x86_64-linux-gnu'/('lib'+lib+'.so');p.unlink(missing_ok=True);p.symlink_to(system)
PY
