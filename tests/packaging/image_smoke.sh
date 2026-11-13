#!/usr/bin/env bash
# The app image, started the way deploy/docker/compose.yaml starts it, on a test port: it answers its health check, it
# runs as a non-root user on a read-only root filesystem with no capability, the panel refuses a foreign Host header, the
# AI setting reaches the panel's settings file, it stops on SIGTERM at once (tini passes the signal on), and a restart
# keeps what the data volume holds. With --selftest it also builds the example resume and deck inside the container.
# Everything it creates (the container, two volumes) is removed at the end; no other container is touched.
#
#   tests/packaging/image_smoke.sh [image] [--selftest]      (default offerowl-app:local)
#
# IMAGE_SMOKE_PORT is the panel's port (18798): the same number inside and outside, because the panel answers only
# requests whose Host header names its own port. IMAGE_SMOKE_WAIT is how long the health check may take (120 s).
set -uo pipefail
IMAGE=offerowl-app:local
SELFTEST=0
for arg in "$@"; do
  case "$arg" in
    --selftest) SELFTEST=1 ;;
    *) IMAGE="$arg" ;;
  esac
done
PORT=${IMAGE_SMOKE_PORT:-18798}
WAIT=${IMAGE_SMOKE_WAIT:-120}
NAME="offerowl-smoke-$$"                              # starts with offerowl, and the PID keeps two runs apart
command -v docker > /dev/null || { echo "tests/packaging/image_smoke.sh: docker is not installed" >&2; exit 2; }
# Something else on the port could answer in the container's place; a run on a busy port tells nothing, so it stops here.
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/health"; then
  echo "tests/packaging/image_smoke.sh: port $PORT is already in use; choose another with IMAGE_SMOKE_PORT" >&2
  exit 2
fi
cleanup() {
  docker rm -f "$NAME" > /dev/null 2>&1
  docker volume rm "$NAME-data" "$NAME-out" > /dev/null 2>&1
  echo "container $NAME and its volumes removed"
}
trap cleanup EXIT
PASS=0
FAIL=0
check() {   # check <name> <command...>: the command's success is the check
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then echo "  ok $name"; PASS=$((PASS + 1)); else echo "  FAIL $name"; FAIL=$((FAIL + 1)); fi
}
dx() { docker exec "$NAME" "$@"; }
CPUS="$(docker info --format '{{.NCPU}}' 2>/dev/null || echo 1)"   # the cap compose.yaml gives, never more than Docker has
CPUS="$(awk -v have="$CPUS" 'BEGIN { print (have + 0 >= 6 || have + 0 <= 0) ? 6 : have }')"
start() {   # the flags compose.yaml gives the container, with a test port and this run's volumes
  docker run -d --name "$NAME" --read-only --tmpfs /tmp:size=1g,mode=1777 --cap-drop ALL --security-opt no-new-privileges:true \
    --pids-limit 512 --memory 4g --cpus "$CPUS" -e "OFFEROWL_PANEL_PORT=$PORT" -e OFFEROWL_LLM=openai-compat \
    -e OFFEROWL_LLM_URL=http://models.example.invalid:11434 -e OFFEROWL_LLM_MODEL=smoke-model \
    -p "127.0.0.1:$PORT:$PORT" -v "$NAME-data:/data" -v "$NAME-out:/work/output" "$IMAGE" > /dev/null
}
healthy() {   # wait until Docker's own health check says healthy
  for _ in $(seq "$WAIT"); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2> /dev/null)" = healthy ] && return 0
    sleep 1
  done
  return 1
}

echo "[start]"
check "the container starts" start
check "its health check turns healthy" healthy
if [ "$FAIL" -gt 0 ]; then
  docker logs --tail 30 "$NAME" 2>&1 | sed 's/^/  log: /'
  echo "==== $PASS passed, $FAIL failed (stopped: nothing else can be checked) ===="
  exit 1
fi

echo "[the panel]"
check "/health says offerowl" test "$(curl -sf -m 5 "http://127.0.0.1:$PORT/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["app"])')" = offerowl
check "the page is served" curl -sf -m 5 -o /dev/null "http://127.0.0.1:$PORT/"
check "a foreign Host header is refused (403)" test "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H 'Host: evil.example' "http://127.0.0.1:$PORT/health")" = 403
check "the container's published port is on the host's loopback only" test "$(docker port "$NAME" "$PORT/tcp" | head -1)" = "127.0.0.1:$PORT"

echo "[the container's hardening]"
check "runs as user 10001" test "$(dx id -u)" = 10001
check "the root filesystem is read-only" bash -c "! docker exec $NAME touch /work/x"
check "the data folder is writable" dx touch /data/probe
check "the engine's output folder is writable" dx touch /work/output/probe
check "no capability is left" test "$(dx sh -c "grep CapEff /proc/1/status | tr -d '[:space:]'")" = CapEff:0000000000000000
check "the first process is tini" test "$(dx cat /proc/1/comm)" = tini
check "the engine knows it is inside a container (/.dockerenv)" dx test -e /.dockerenv

echo "[the AI backend from the environment]"
check "the panel's backend is openai-compat" dx python3 -c "import json; s = json.load(open('/data/settings.json')); assert s['backend'] == 'openai-compat', s"
check "the panel's model server address is the environment's" dx python3 -c "import json; s = json.load(open('/data/settings.json')); assert s['llm_url'] == 'http://models.example.invalid:11434', s"
check "the panel's model name is the environment's" dx python3 -c "import json; s = json.load(open('/data/settings.json')); assert s['llm_model'] == 'smoke-model', s"

echo "[the doctor, inside the container]"
check "offerowl doctor finds the tools of the container" dx offerowl-doctor --only render,libs,fonts,python

if [ "$SELFTEST" = 1 ]; then
  echo "[the self-test, inside the container]"
  check "offerowl selftest passes (resume, deck, checks, OCR)" bash -c "docker exec -e OFFEROWL_LANG=en $NAME offerowl selftest | tail -1 | grep -q 'PASS'"
fi

echo "[stop and start again]"
dx touch /data/kept > /dev/null 2>&1
STARTED=$(date +%s)
check "docker stop ends the container" docker stop -t 10 "$NAME"
check "it stops within 5 seconds (SIGTERM reaches the panel)" test "$(( $(date +%s) - STARTED ))" -lt 5
check "it can start again" docker start "$NAME"
check "its health check turns healthy again" healthy
check "what the data volume held is still there" dx test -e /data/kept

echo "==== $PASS passed, $FAIL failed ===="
[ "$FAIL" -eq 0 ]
