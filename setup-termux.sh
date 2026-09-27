#!/data/data/com.termux/files/usr/bin/sh
# Preparação guiada do Ysha Agente no Termux.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  if command -v pkg >/dev/null 2>&1; then
    pkg install -y python
  else
    echo "Instale Python 3.10 ou mais recente e execute este script novamente." >&2
    exit 1
  fi
fi

if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo "É necessário Python 3.10 ou mais recente." >&2
  exit 1
fi
exec python3 "$ROOT/scripts/setup_termux.py"
