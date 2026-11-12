#!/usr/bin/env bash
# The Helm chart on a throwaway kind cluster: what only a running cluster shows. The pod gets ready (so the probes and
# the Host header they send work), the panel answers through port-forward, it runs as a non-root user on a read-only
# root filesystem, what the panel saves survives a replaced pod (the claim works), the chart's AI settings reach the
# panel's settings file, a foreign Host header is refused, helm test passes, and helm uninstall leaves the claim.
# The cluster and its kubeconfig are removed at the end whatever happens; ~/.kube/config is never touched.
#
#   tests/packaging/chart_e2e.sh [app image]          (default offerowl-app:local, built with docker build -f deploy/docker/Dockerfile .)
#
# The chart is installed into a namespace that enforces the "restricted" Pod Security level. CHART_E2E_PORT is the panel's port in the pod and the local port of the forward (18797): one number, because the panel
# answers only requests whose Host header names its own port. CHART_E2E_WAIT is how long helm waits (5m), and
# CHART_E2E_KEEP=1 leaves the cluster in place when you want to look at it. KIND, HELM and
# KUBECTL name other binaries. It needs docker, kind, helm, kubectl and curl, and pulls the
# kind node image once.
set -uo pipefail
KIND=${KIND:-kind}
HELM=${HELM:-helm}
KUBECTL=${KUBECTL:-kubectl}
REPO="$(cd "$(dirname "$0")/../.." && pwd)"          # the repository: this file is in tests/packaging/
WORK="$(mktemp -d "${TMPDIR:-/tmp}/offerowl-chart-e2e.XXXXXX")"   # the logs and the kubeconfig
NAME="offerowl-e2e-$$"                                # a cluster of this run's own
NS=offerowl
PORT=${CHART_E2E_PORT:-18797}                         # the panel's port in the pod and on the forward
WAIT=${CHART_E2E_WAIT:-5m}
IMAGE=${1:-offerowl-app:local}
export KUBECONFIG="$WORK/kubeconfig"                  # this cluster's alone
for tool in docker "$KIND" "$HELM" "$KUBECTL" curl; do
  command -v "$tool" > /dev/null || { echo "tests/packaging/chart_e2e.sh: $tool is not installed" >&2; exit 2; }
done
# Something else on the port would answer in the pod's place; a run on a busy port tells nothing, so it stops here.
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORT/health"; then
  echo "tests/packaging/chart_e2e.sh: port $PORT is already in use; choose another with CHART_E2E_PORT" >&2
  exit 2
fi

PF_PID=""
SVC=offerowl   # the Service forward() reaches: the release's own, or one person's when the release has tenants
cleanup() {
  [ -n "$PF_PID" ] && kill "$PF_PID" 2> /dev/null   # the forward always ends with the run
  if [ "${CHART_E2E_KEEP:-0}" = 1 ]; then   # CHART_E2E_KEEP=1 leaves the cluster to look at
    echo "cluster $NAME kept (kubeconfig $KUBECONFIG); delete it with: kind delete cluster --name $NAME"
    return
  fi
  "$KIND" delete cluster --name "$NAME" > /dev/null 2>&1
  echo "cluster $NAME deleted (logs in $WORK)"
}
trap cleanup EXIT
PASS=0
FAIL=0
check() {   # check <name> <command...>: the command's success is the check
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then echo "  ok $name"; PASS=$((PASS + 1)); else echo "  FAIL $name"; FAIL=$((FAIL + 1)); fi
}
kc() { "$KUBECTL" --namespace "$NS" "$@"; }
forward() {   # forward the panel's port, replacing an earlier forward
  if [ -n "$PF_PID" ]; then   # the earlier one is stopped and waited for, so its port is free and it cannot answer any more
    kill "$PF_PID" 2> /dev/null
    wait "$PF_PID" 2> /dev/null
  fi
  # kubectl itself runs in the background (not the kc function, whose subshell would keep running after a kill)
  "$KUBECTL" --namespace "$NS" port-forward "svc/$SVC" "$PORT:$PORT" > "$WORK/forward.log" 2>&1 &
  PF_PID=$!
  for _ in $(seq 40); do
    # the answer counts only while this forward is alive: if it could not bind (the port is taken by another program),
    # kubectl exits, and whatever else answers on the port is not the pod
    kill -0 "$PF_PID" 2> /dev/null || return 1
    curl -sf -m 2 "http://127.0.0.1:$PORT/health" > /dev/null && return 0
    sleep 1
  done
  return 1
}
panel_setting() {   # panel_setting <key>: a value of the panel's saved settings, read through the API
  curl -sf -m 5 "http://127.0.0.1:$PORT/api/v1/state" | python3 -c "import json,sys; print(json.load(sys.stdin)['settings'][sys.argv[1]])" "$1"
}
diagnose() {   # what a failed install leaves to read
  echo "  -- pods"; kc get pods -o wide 2>&1 | sed 's/^/     /'
  echo "  -- events"; kc get events --sort-by=.lastTimestamp 2>&1 | tail -20 | sed 's/^/     /'
  echo "  -- log"; kc logs deploy/offerowl --tail=30 2>&1 | sed 's/^/     /'
}

echo "[cluster]"
"$KIND" create cluster --name "$NAME" --wait 180s > "$WORK/kind_create.log" 2>&1 \
  || { echo "cluster create failed: $(tail -3 "$WORK/kind_create.log")"; exit 1; }
"$KIND" load docker-image "$IMAGE" --name "$NAME" > "$WORK/kind_load.log" 2>&1 || { echo "image load failed: $(tail -3 "$WORK/kind_load.log")"; exit 1; }
"$KUBECTL" get nodes --no-headers | sed 's/^/  /'

echo "[install]"
# The namespace enforces the strictest Pod Security level, so the API server itself refuses a pod that is not hardened
if ! "$KUBECTL" create namespace "$NS" > /dev/null \
  || ! "$KUBECTL" label namespace "$NS" pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/enforce-version=latest > /dev/null; then
  echo "could not prepare the namespace"
  exit 1
fi
IMG_ARGS=(--set "image.repository=${IMAGE%:*}" --set "image.tag=${IMAGE##*:}" --set image.pullPolicy=Never --set "service.panelPort=$PORT")
"$HELM" install offerowl "$REPO/deploy/helm/offerowl" --namespace "$NS" "${IMG_ARGS[@]}" \
  --wait --timeout "$WAIT" > "$WORK/helm_install.log" 2>&1
check "helm install, the pod is ready in a namespace that enforces the restricted Pod Security level" grep -q "STATUS: deployed" "$WORK/helm_install.log"
check "the namespace does enforce it" test "$(kc get namespace "$NS" -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}')" = restricted
kc get pods --no-headers | sed 's/^/  /'
if [ "$FAIL" -gt 0 ]; then
  tail -5 "$WORK/helm_install.log" | sed 's/^/  helm: /'
  diagnose
  echo "==== $PASS passed, $FAIL failed (stopped: nothing else can be checked without the pod) ===="
  exit 1
fi
check "the claim is bound" test "$(kc get pvc offerowl-data -o jsonpath='{.status.phase}')" = Bound

echo "[the panel through port-forward]"
check "port-forward reaches /health" forward
check "/health says offerowl" test "$(curl -sf -m 5 "http://127.0.0.1:$PORT/health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["app"])')" = offerowl
check "the page is served" curl -sf -m 5 "http://127.0.0.1:$PORT/" -o /dev/null
check "a foreign Host header is refused (403)" test "$(curl -s -m 5 -o /dev/null -w '%{http_code}' -H 'Host: evil.example' "http://127.0.0.1:$PORT/health")" = 403
check "the panel's first settings: the agent is off (backend none)" test "$(panel_setting backend)" = none

echo "[the pod's hardening]"
check "runs as user 10001" test "$(kc exec deploy/offerowl -- id -u)" = 10001
check "the root filesystem is read-only" bash -c "! $KUBECTL --namespace $NS exec deploy/offerowl -- touch /work/x"
check "the data folder is writable" kc exec deploy/offerowl -- touch /data/probe
check "the engine's output folder is writable" kc exec deploy/offerowl -- touch /work/output/probe
check "no capability is left" test "$(kc exec deploy/offerowl -- sh -c "grep CapEff /proc/1/status | tr -d '[:space:]'")" = CapEff:0000000000000000

echo "[a saved setting survives a replaced pod]"
check "the panel saves a setting" curl -sf -m 5 -X POST "http://127.0.0.1:$PORT/api/v1/settings" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:$PORT" -d '{"lang":"ko"}'
check "the setting is read back" test "$(panel_setting lang)" = ko
kc delete pod -l app.kubernetes.io/name=offerowl --wait=true > /dev/null 2>&1
kc rollout status deploy/offerowl --timeout "$WAIT" > /dev/null 2>&1
check "the new pod serves the panel again" forward
check "the setting is still there (the claim kept it)" test "$(panel_setting lang)" = ko

ai_diagnose() {   # what the pod holds when the chart's AI values did not reach the panel
  echo "  -- env"; kc exec deploy/offerowl -- sh -c 'env | grep OFFEROWL_LLM' 2>&1 | sed 's/^/     /'
  echo "  -- settings.json"; kc exec deploy/offerowl -- cat /data/settings.json 2>&1 | sed 's/^/     /'
  echo "  -- pods"; kc get pods 2>&1 | sed 's/^/     /'
}

echo "[the AI backend from the chart's values]"
"$HELM" upgrade offerowl "$REPO/deploy/helm/offerowl" --namespace "$NS" "${IMG_ARGS[@]}" \
  --set ai.backend=openai-compat --set ai.url=http://models.example.invalid:11434 --set ai.model=test-model \
  --wait --timeout "$WAIT" > "$WORK/helm_upgrade.log" 2>&1
check "helm upgrade with a local model server" grep -q "STATUS: deployed" "$WORK/helm_upgrade.log"
check "the new pod serves the panel again" forward
check "the panel's backend is openai-compat" test "$(panel_setting backend)" = openai-compat
check "the panel's model server address is the chart's" test "$(panel_setting llm_url)" = http://models.example.invalid:11434
check "the panel's model name is the chart's" test "$(panel_setting llm_model)" = test-model
check "the setting made before the upgrade is kept" test "$(panel_setting lang)" = ko
[ "$FAIL" -eq 0 ] || ai_diagnose

echo "[helm test, uninstall]"
check "helm test passes" "$HELM" test offerowl --namespace "$NS" --timeout 3m
"$HELM" uninstall offerowl --namespace "$NS" > /dev/null 2>&1
check "helm uninstall leaves the claim with the documents" kc get pvc offerowl-data
check "helm uninstall removes the deployment" bash -c "! $KUBECTL --namespace $NS get deploy offerowl"

echo "[two people on one release]"
# Each person in tenants gets an Offerowl of their own: their own pod, claim and Service, and what one saves the other never
# sees. Bob's claim takes the size of his own values.
jobs_seen() {   # how many applications the forwarded panel holds
  curl -sf -m 5 "http://127.0.0.1:$PORT/api/v1/state" | python3 -c "import json,sys; print(len(json.load(sys.stdin)['jobs']))"
}
"$HELM" install team "$REPO/deploy/helm/offerowl" --namespace "$NS" "${IMG_ARGS[@]}" \
  --set 'tenants[0].name=alice' --set 'tenants[1].name=bob' --set 'tenants[1].persistence.size=1Gi' \
  --wait --timeout "$WAIT" > "$WORK/helm_team.log" 2>&1
check "helm install with two people, both pods ready" grep -q "STATUS: deployed" "$WORK/helm_team.log"
check "two deployments, one for each" test "$(kc get deploy -l app.kubernetes.io/instance=team --no-headers | wc -l)" = 2
check "alice's claim is bound" test "$(kc get pvc team-offerowl-alice-data -o jsonpath='{.status.phase}')" = Bound
check "bob's claim is bound, at his own size" test "$(kc get pvc team-offerowl-bob-data -o jsonpath='{.spec.resources.requests.storage}')" = 1Gi
SVC=team-offerowl-alice
check "alice's panel through port-forward" forward
check "alice adds an application" curl -sf -m 10 -X POST "http://127.0.0.1:$PORT/api/v1/jobs" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:$PORT" \
  -d '{"company":"Acme","role":"Platform engineer","posting":"Acme builds payment systems. You will run its Kubernetes platform."}'
check "alice's panel lists it" test "$(jobs_seen)" = 1
SVC=team-offerowl-bob
check "bob's panel through port-forward" forward
check "bob's panel does not list alice's application (a workspace of his own)" test "$(jobs_seen)" = 0
SVC=team-offerowl-alice
check "alice's panel again" forward
check "alice's application is still hers" test "$(jobs_seen)" = 1
check "helm test passes for both people" "$HELM" test team --namespace "$NS" --timeout 3m
"$HELM" uninstall team --namespace "$NS" > /dev/null 2>&1
check "helm uninstall leaves both people's claims" kc get pvc team-offerowl-alice-data team-offerowl-bob-data

echo "==== $PASS passed, $FAIL failed ===="
[ "$FAIL" -eq 0 ]
