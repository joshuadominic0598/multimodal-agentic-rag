#!/bin/zsh
set -eu
cd -- "${0:A:h:h}"
AGENTIC_RAG_PYTHON="${AGENTIC_RAG_PYTHON:-python3}"
if ! "$AGENTIC_RAG_PYTHON" -c 'import sys; assert sys.version_info >= (3,11)' 2>/dev/null; then
  print -u2 "Python 3.11 or newer is required. Set AGENTIC_RAG_PYTHON to a supported Python executable."
  exit 1
fi
"$AGENTIC_RAG_PYTHON" -m venv .venv
.venv/bin/python -m pip install -e .
print 'Ready. Double-click scripts/start.command to open Agentic RAG.'
