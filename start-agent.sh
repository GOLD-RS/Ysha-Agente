#!/data/data/com.termux/files/usr/bin/sh
# Carrega configuração privada e inicia o servidor em primeiro plano.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

if [ ! -f .env ]; then
  echo "Arquivo .env não encontrado. Execute ./setup-termux.sh primeiro." >&2
  exit 1
fi
set -a
. ./.env
set +a

if [ -z "${AGENT_API_KEY:-}" ]; then
  echo "AGENT_API_KEY está vazio. Execute ./setup-termux.sh para configurar a API." >&2
  exit 1
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m termux_agent
