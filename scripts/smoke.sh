#!/usr/bin/env bash
# Smoke test: boot the app on a random port, probe the main endpoints,
# kill the server, print PASS/FAIL. Usage: bash scripts/smoke.sh
set -u
cd "$(dirname "$0")/.."

PORT=$(( (RANDOM % 2000) + 8000 ))
DB="$(mktemp -u).db"
LOG="$(mktemp)"
export CHASER_DB="$DB" DISABLE_SCHEDULER=1

python -m uvicorn app.main:app --port "$PORT" --log-level warning >"$LOG" 2>&1 &
PID=$!

fail() {
  echo "SMOKE: FAIL ($1)"
  kill "$PID" 2>/dev/null
  rm -f "$DB" "$LOG"
  exit 1
}

# wait for boot (max ~15 s)
for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  kill -0 "$PID" 2>/dev/null || fail "server died on boot (see $LOG)"
  sleep 0.5
done

curl -sf "http://127.0.0.1:$PORT/api/health" | grep -q '"ok"' || fail "/api/health"
curl -sf "http://127.0.0.1:$PORT/" | grep -q "Payment Chaser" || fail "GET / (UI)"
curl -sf "http://127.0.0.1:$PORT/api/dashboard" | grep -q "overdue_count" || fail "/api/dashboard"

CID=$(curl -sf -X POST "http://127.0.0.1:$PORT/api/clients" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Smoke Co","email":"smoke@test.ua","language":"en"}' \
  | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
[ -n "$CID" ] || fail "POST /api/clients"

curl -sf -X POST "http://127.0.0.1:$PORT/api/invoices" \
  -H 'Content-Type: application/json' \
  -d "{\"number\":\"SMOKE-1\",\"client_id\":$CID,\"amount\":42,\"issued_date\":\"2026-01-01\",\"due_date\":\"2026-01-02\",\"items\":[{\"item\":\"Smoke item\",\"qty\":1,\"price\":42}]}" \
  | grep -q '"status":"draft"' || fail "POST /api/invoices"
INV_ID=$(curl -sf "http://127.0.0.1:$PORT/api/invoices" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)
[ -n "$INV_ID" ] || fail "GET /api/invoices"
curl -sf -X PATCH "http://127.0.0.1:$PORT/api/invoices/$INV_ID" \
  -H 'Content-Type: application/json' -d '{"status":"sent"}' >/dev/null || fail "PATCH status=sent"

curl -sf -X POST "http://127.0.0.1:$PORT/api/engine/run" | grep -q "SMOKE-1" || fail "POST /api/engine/run"
curl -sf "http://127.0.0.1:$PORT/api/outbox" | grep -q "Smoke item" || fail "/api/outbox (letter with line items)"
PREVIEW=$(curl -sf "http://127.0.0.1:$PORT/api/invoices/1/preview") || fail "GET /api/invoices/1/preview"
echo "$PREVIEW" | grep -q "Invoice line items" || fail "preview body"

kill "$PID" 2>/dev/null
rm -f "$DB" "$LOG"
echo "SMOKE: PASS"
