#!/data/data/com.termux/files/usr/bin/sh
# Inicia o servidor; o Python lê .env como dados, nunca como shell.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

if [ ! -f .env ]; then
  echo "Arquivo .env não encontrado. Execute ./setup-termux.sh primeiro." >&2
  exit 1
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m termux_agent
