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

if [ -z "${AGENT_API_KEY:-}" ] || [ -z "${AGENT_BASE_URL:-}" ] || [ -z "${AGENT_MODEL:-}" ]; then
  echo "Configure AGENT_API_KEY, AGENT_BASE_URL e AGENT_MODEL com ./setup-termux.sh." >&2
  exit 1
fi
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m termux_agent
