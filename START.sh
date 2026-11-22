#!/usr/bin/env bash
# Start the existing validated DAT pipeline and integrated graphical application.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$ROOT/qemu-machine/qemu-src/build/qemu-system-arm" ]]; then
  echo 'QEMU has not been built. Run: bash INSTALL.sh' >&2
  exit 1
fi
exec python3 "$ROOT/scripts/start_system.py" "$@"
