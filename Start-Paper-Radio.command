#!/bin/bash
# Double-click this file on macOS. It opens Paper Radio in your browser.
set -u
cd -- "$(dirname -- "$0")" || exit 1

python_bin=""
for candidate in python3 python /opt/anaconda3/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    python_bin="$candidate"
    break
  fi
done

if [ -z "$python_bin" ]; then
  printf '\nPaper Radio requires Python 3.11 or newer. Install Python, then open this launcher again.\n'
  read -r -p 'Press Return to close this window. ' || true
  exit 1
fi

export PYTHONNOUSERSITE=1
if "$python_bin" launch.py; then
  exit 0
else
  result=$?
  printf '\nPaper Radio could not start. The error is shown above.\n'
  read -r -p 'Press Return to close this window. ' || true
  exit "$result"
fi
