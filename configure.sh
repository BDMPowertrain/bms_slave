#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v python3 >/dev/null 2>&1; then
    python3 "$DIR/configure.py" "$@"
elif command -v python >/dev/null 2>&1; then
    python "$DIR/configure.py" "$@"
else
    echo "Python 3 was not found. Install it (e.g. 'sudo apt install python3'" >&2
    echo "or from https://www.python.org/downloads/), then run this script again." >&2
    exit 1
fi
