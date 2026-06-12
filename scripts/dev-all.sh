#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${TMPDIR:-/tmp}/on-mobile-agent-dev-logs"

mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/*.log

cd "$ROOT_DIR"

NGROK_CMD="${NGROK_CMD:-ngrok http 2024}"
BACKEND_FLAGS="${BACKEND_FLAGS:---no-browser --no-reload --port 2024 --tunnel}"
BACKEND_CMD="${BACKEND_CMD:-uv run langgraph dev $BACKEND_FLAGS}"
FRONTEND_CMD="${FRONTEND_CMD:-cd apps/dashboard && bun run dev -- --strictPort}"
OLLAMA_HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
DEV_ALL_KILL_PORTS="${DEV_ALL_KILL_PORTS:-0}"

PIDS=()

cleanup() {
  local status="${1:-$?}"
  echo ""
  echo "🧹 Cerrando procesos..."

  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done

  exit "$status"
}

port_pids() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

require_free_port() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"

  if [[ -z "$pids" ]]; then
    return 0
  fi

  if [[ "$DEV_ALL_KILL_PORTS" == "1" ]]; then
    echo "⚠️  Puerto $port ocupado. Cerrando PIDs: $pids"
    kill $pids 2>/dev/null || true
    sleep 1
    pids="$(port_pids "$port")"
    if [[ -z "$pids" ]]; then
      return 0
    fi
  fi

  echo "❌ Puerto $port ocupado. Cierra estos procesos o ejecuta DEV_ALL_KILL_PORTS=1 make dev-all:"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN || true
  exit 1
}

wait_for_port() {
  local name="$1"
  local port="$2"
  local log_file="$3"
  local pids

  for i in {1..60}; do
    pids="$(port_pids "$port")"
    if [[ -n "$pids" ]]; then
      echo "✅ $name listo en puerto $port"
      return 0
    fi
    sleep 1
  done

  echo "❌ $name no abrió el puerto $port. Últimas líneas de log:"
  tail -80 "$log_file" || true
  exit 1
}

trap 'cleanup $?' EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

echo "🚀 Iniciando ON Mobile Agent dev stack..."
echo "📝 Logs en: $LOG_DIR"
echo ""

echo "0/4 Validando puertos..."
require_free_port 2024
require_free_port 3000

echo "1/4 Verificando Ollama..."
if curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
  echo "✅ Ollama ya está corriendo en $OLLAMA_HOST"
else
  echo "🦙 Iniciando Ollama..."
  ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
  PIDS+=("$!")

  for i in {1..20}; do
    if curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1; then
      echo "✅ Ollama listo"
      break
    fi
    sleep 1
  done
fi

echo "2/4 Iniciando ngrok..."
bash -lc "$NGROK_CMD" > "$LOG_DIR/ngrok.log" 2>&1 &
PIDS+=("$!")

echo "3/4 Iniciando backend..."
bash -lc "$BACKEND_CMD" > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=("$!")

echo "4/4 Iniciando frontend..."
bash -lc "$FRONTEND_CMD" > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

echo "Validando servicios..."
wait_for_port "Backend" 2024 "$LOG_DIR/backend.log"
wait_for_port "Frontend" 3000 "$LOG_DIR/frontend.log"

echo ""
echo "✅ Todo iniciado"
echo ""
echo "Backend:  http://localhost:2024"
echo "Frontend: http://localhost:3000"
echo "Ollama:   $OLLAMA_HOST"
echo "ngrok:    mira $LOG_DIR/ngrok.log"
echo ""
echo "Presiona Ctrl+C para apagar todo."
echo ""

tail -f "$LOG_DIR"/*.log &
PIDS+=("$!")

wait
