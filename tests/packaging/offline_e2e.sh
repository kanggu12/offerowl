#!/usr/bin/env bash
# The app image with no network at all, the way a closed network runs it: it has no route out, and it still reads the example, writes
# with a model server on its own side (a stand-in here), typesets, makes the interview kit and serves its view at /kit/<job>/. A posting's
# link is said to be unreachable, and a pasted posting works. Everything it creates is removed at the end.
#
#   tests/packaging/offline_e2e.sh [image]      (default offerowl-app:local)
set -uo pipefail
IMAGE=${1:-offerowl-app:local}
NAME="offerowl-offline-$$"                            # starts with offerowl, and the PID keeps two runs apart
command -v docker > /dev/null || { echo "tests/packaging/offline_e2e.sh: docker is not installed" >&2; exit 2; }
cleanup() {
  docker rm -f "$NAME" > /dev/null 2>&1
  docker volume rm "$NAME-data" "$NAME-out" > /dev/null 2>&1
  echo "container $NAME and its volumes removed"
}
trap cleanup EXIT
# The flags compose.yaml gives the container, with no network in place of its published ports; the model server is on the container's own loopback
docker run -d --name "$NAME" --network none --read-only --tmpfs /tmp:size=1g,mode=1777 --cap-drop ALL --security-opt no-new-privileges:true \
  -e OFFEROWL_LLM=openai-compat -e OFFEROWL_LLM_URL=http://127.0.0.1:18080 -e OFFEROWL_LLM_MODEL=standin \
  -v "$NAME-data:/data" -v "$NAME-out:/work/output" "$IMAGE" > /dev/null || exit 1
docker exec -d "$NAME" python3 apps/api/standin.py serve 18080 > /dev/null || exit 1   # the stand-in for a model server in the closed network
docker exec -i "$NAME" python3 - <<'PY'
import json, socket, sys, time, urllib.error, urllib.parse, urllib.request
BASE = "http://127.0.0.1:8797"  # the panel, from inside the container
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # no proxy, on purpose
FAILED = []  # what did not hold
def check(name, good, detail=""):  # one line per check
    print(("  ok " if good else "  FAIL ") + name + ("" if good else f": {detail}"), flush=True)
    if not good:
        FAILED.append(name)
def get(path, raw=False):  # a read
    with opener.open(BASE + path, timeout=120) as r:
        body = r.read()
    return body if raw else json.loads(body)
def post(path, body):  # a write; a refusal comes back as its own answer
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener.open(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"status": e.code, **json.loads(e.read() or b"{}")}
def wait(key, seconds=300):  # until a task ends
    end = time.time() + seconds
    while time.time() < end:
        t = get("/api/v1/state")["tasks"].get(key) or {}
        if t.get("state") in ("done", "error"):
            return t
        time.sleep(0.5)
    return {"state": "timeout"}
for _ in range(120):  # the server starts
    try:
        get("/api/v1/health")
        break
    except OSError:
        time.sleep(1)
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    out = True
except OSError:
    out = False
check("there is no route out of this container", not out)
post("/api/v1/example", {"lang": "ko"})
check("the example is read", wait("ingest").get("state") == "done")
post("/api/v1/facts/keep-all", {})
link = post("/api/v1/jobs", {"company": "링크", "url": "https://example.com/job"})  # as the job form sends a link
check("a posting's link says it cannot be reached", link.get("status") == 400, str(link)[:200])
posting = "# 델타페이 백엔드 플랫폼 엔지니어\n\n담당 업무\n- 결제 승인 서비스 개발과 운영\n- Kubernetes 배포 플랫폼 운영\n\n자격 요건\n- Go 또는 Java 경험\n"
job = post("/api/v1/jobs", {"company": "델타페이", "role": "백엔드 플랫폼 엔지니어", "posting": posting}).get("job")
check("a pasted posting is added", bool(job), str(job))
check("the posting is analysed", wait(f"analyze:{job}").get("state") == "done")
state = get("/api/v1/state")
check("the agent is the model server here", (state["agent"].get("backend"), state["agent"].get("state")) == ("openai-compat", "ready"), str(state["agent"])[:200])
wrote = wait(post("/api/v1/jobs/write", {"job": job, "lang": "ko"}).get("task", ""))
check("the resume is written by that server", wrote.get("state") == "done", str(wrote)[:300])
quoted = urllib.parse.quote(job)
live = get(f"/api/v1/jobs/{quoted}/deck/ko")
check("the deck is shown without a PDF", live.get("slides", 0) > 3, str({k: v for k, v in live.items() if k != "html"})[:200])
post("/api/v1/jobs/build", {"job": job, "lang": "ko", "theme": "navy", "maxPages": 3, "cover": False})
built = wait(f"build:{job}", 600)
res = built.get("result") or {}
check("the PDFs are made", built.get("state") == "done" and res.get("issues") == 0, str(built)[:300])
check("the resume PDF comes through the API", get(f"/api/v1/jobs/{quoted}/files/ko/resume.pdf", raw=True)[:5] == b"%PDF-")
check("the plain resume too", "홍길동" in get(f"/api/v1/jobs/{quoted}/files/ko/resume.txt", raw=True).decode("utf-8"))
kit = post("/api/v1/interview/kit", {"job": job})
check("the interview kit's question map is made", kit.get("questions", 0) > 0, str(kit)[:200])
started = post("/api/v1/interview/start", {"job": job})
check("the interview kit's view starts", started.get("started") is True, str(started)[:200])
with opener.open(BASE + f"/kit/{quoted}/", timeout=60) as r:  # the view, through the panel: the container's one port
    check("the interview view answers at the panel's own address", r.status == 200 and b"<html" in r.read(65536).lower())
print(f"==== {len(FAILED)} failed ====", flush=True)
sys.exit(1 if FAILED else 0)
PY
