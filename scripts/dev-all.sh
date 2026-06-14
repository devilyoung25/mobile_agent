#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${TMPDIR:-/tmp}/on-mobile-agent-dev-logs"

mkdir -p "$LOG_DIR"
rm -f "$LOG_DIR"/*.log

cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

NGROK_CMD="${NGROK_CMD:-ngrok http 2024}"
BACKEND_FLAGS="${BACKEND_FLAGS:---no-browser --no-reload --port 2024 --tunnel}"
BACKEND_CMD="${BACKEND_CMD:-uv run langgraph dev $BACKEND_FLAGS}"
FRONTEND_CMD="${FRONTEND_CMD:-cd apps/dashboard && bun run dev -- --strictPort}"
MODEL_GATEWAY_BASE_URL="${MODEL_GATEWAY_BASE_URL:-}"
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

print_studio_url() {
  local studio_url
  studio_url="$(
    sed $'s/\x1b\\[[0-9;]*m//g' "$LOG_DIR/backend.log" \
      | grep -Eo 'https://smith\.langchain\.com/studio/[^[:space:]]+' \
      | tail -1 || true
  )"

  if [[ -n "$studio_url" ]]; then
    echo "LangGraph Studio: $studio_url"
  elif grep -q -- "--tunnel" <<< "$BACKEND_CMD"; then
    echo "⚠️  No encontré URL de Studio en backend.log todavía."
  fi

  if grep -q "Tunnel server stopped" "$LOG_DIR/backend.log"; then
    echo "⚠️  El tunnel de LangGraph se detuvo. Studio remoto no podrá usar localhost:2024."
  fi
}

trap 'cleanup $?' EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

echo "🚀 Iniciando ON Mobile Agent dev stack..."
echo "📝 Logs en: $LOG_DIR"
echo ""

echo "0/3 Validando puertos..."
require_free_port 2024
require_free_port 3000

echo "1/3 Verificando ON Model Gateway..."
if [[ -z "$MODEL_GATEWAY_BASE_URL" ]]; then
  echo "❌ MODEL_GATEWAY_BASE_URL no está configurado."
  echo "   Levanta ON Model Gateway primero y configura, por ejemplo:"
  echo "   MODEL_GATEWAY_BASE_URL=http://localhost:4000/v1"
  exit 1
fi

MODEL_GATEWAY_HEALTH_URL="${MODEL_GATEWAY_BASE_URL%/v1}/health"
if curl -fsS "$MODEL_GATEWAY_HEALTH_URL" >/dev/null 2>&1; then
  echo "✅ ON Model Gateway listo en $MODEL_GATEWAY_HEALTH_URL"
else
  echo "❌ ON Model Gateway no responde en $MODEL_GATEWAY_HEALTH_URL"
  echo "   Levanta ON Model Gateway primero y vuelve a ejecutar make dev-all."
  exit 1
fi

echo "2/3 Iniciando ngrok..."
bash -lc "$NGROK_CMD" > "$LOG_DIR/ngrok.log" 2>&1 &
PIDS+=("$!")

echo "3/3 Iniciando backend..."
bash -lc "$BACKEND_CMD" > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=("$!")

echo "Iniciando frontend..."
bash -lc "$FRONTEND_CMD" > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

echo "Validando servicios..."
wait_for_port "Backend" 2024 "$LOG_DIR/backend.log"
wait_for_port "Frontend" 3000 "$LOG_DIR/frontend.log"
sleep 3
print_studio_url

echo ""
echo "✅ Todo iniciado"
echo ""
echo "Backend:  http://localhost:2024"
echo "Frontend: http://localhost:3000"
echo "Gateway:  $MODEL_GATEWAY_BASE_URL"
echo "ngrok:    mira $LOG_DIR/ngrok.log"
echo ""
echo "Presiona Ctrl+C para apagar todo."
echo ""

tail -f "$LOG_DIR"/*.log &
PIDS+=("$!")

wait
