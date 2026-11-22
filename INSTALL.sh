#!/usr/bin/env bash
# Source installation. Never downloads Icom firmware or changes system packages implicitly.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --install-deps ]]; then
  shift
  [[ -r /etc/os-release ]] || { echo 'Cannot identify this distribution.' >&2; exit 1; }
  . /etc/os-release
  [[ "${ID:-}" == ubuntu || "${ID:-}" == debian || " ${ID_LIKE:-} " == *' debian '* ]] || { echo 'Install dependencies manually; see docs/INSTALLATION.md.' >&2; exit 1; }
  echo 'System packages will be installed with apt. Review this list:'
  PACKAGES=(build-essential git pkg-config ninja-build python3 python3-venv python3-tk libglib2.0-dev libpixman-1-dev zlib1g-dev)
  printf ' %s' "${PACKAGES[@]}"; printf '\n'
  read -r -p 'Continue with apt installation? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y ]] || exit 1
  SUDO=(); (( EUID==0 )) || SUDO=(sudo)
  "${SUDO[@]}" apt-get update
  "${SUDO[@]}" apt-get install --no-install-recommends "${PACKAGES[@]}"
fi
for tool in git cc c++ make pkg-config ninja python3; do
  command -v "$tool" >/dev/null || { echo "Missing $tool. See docs/INSTALLATION.md or use --install-deps." >&2; exit 1; }
done
python3 -c 'import tkinter, venv' || { echo 'Python Tkinter/venv is required.' >&2; exit 1; }
if ! pkg-config --exists glib-2.0 pixman-1 zlib && [[ ! -d "$ROOT/tools/sysroot" ]]; then
  echo 'Missing development headers. Use --install-deps, or Ubuntu 24.04 local extraction:' >&2
  echo 'bash scripts/prepare_deps.sh  (downloads/extracts packages locally; no sudo)' >&2
  exit 1
fi
bash "$ROOT/scripts/build.sh"
if [[ "${1:-}" == --build-only ]]; then exit 0; fi
exec bash "$ROOT/START.sh" "$@"
