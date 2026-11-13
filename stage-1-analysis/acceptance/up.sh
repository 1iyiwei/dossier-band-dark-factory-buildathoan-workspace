#!/usr/bin/env bash
# One command: start the mock web (serving the analyst corpus) and a service image on a private
# docker network, measure start-to-healthy, run the acceptance tests, then remove what it started.
#
#   ./up.sh <service-image-tag> [run.sh args...]
#   ./up.sh --build <dir-with-Dockerfile> [run.sh args...]
#
# Env: KICKOFF (kickoff package root), SUFFIX (container/network suffix, default "analyst"),
#      SVC_PORT (18001), MOCK_PORT (18081), KEEP=1 to leave the containers running.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KICKOFF="${KICKOFF:-$(cd "$HERE/../../../../sf-buildathon-2026" && pwd)}"
SUFFIX="${SUFFIX:-analyst}"
SVC_PORT="${SVC_PORT:-18001}"
MOCK_PORT="${MOCK_PORT:-18081}"
NET="dossier-$SUFFIX"
WEB="web-$SUFFIX"
SVC="svc-$SUFFIX"

if [[ "${1:-}" == "--build" ]]; then
  IMAGE="dossier-svc-$SUFFIX"
  docker build -t "$IMAGE" "$2"
  shift 2
else
  IMAGE="${1:?usage: up.sh <image> | --build <dir>}"
  shift
fi

docker build -q -t dossier-web "$KICKOFF/challenges/dossier/web" >/dev/null
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null

cleanup() {
  if [[ "${KEEP:-0}" != "1" ]]; then
    docker rm -f "$SVC" "$WEB" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
docker rm -f "$SVC" "$WEB" >/dev/null 2>&1 || true

docker run --rm -d --name "$WEB" --network "$NET" -e MOCK_ADMIN_TOKEN=local-admin \
  -v "$HERE/corpus:/data/corpus:ro" -p "$MOCK_PORT:8080" dossier-web >/dev/null
for _ in $(seq 1 60); do
  curl -fs "http://localhost:$MOCK_PORT/_mock/health" >/dev/null 2>&1 && break
  sleep 1
done

start=$(date +%s)
docker run --rm -d --name "$SVC" --network "$NET" --cpus 2 --memory 3g -p "$SVC_PORT:8000" \
  -e PORT=8000 \
  -e NIMBLE_API_KEY=local -e NIMBLE_BASE_URL="http://$WEB:8080/nimble" \
  -e TAVILY_API_KEY=local -e TAVILY_BASE_URL="http://$WEB:8080/tavily" \
  "$IMAGE" >/dev/null
healthy=""
for _ in $(seq 1 120); do
  if curl -fs "http://localhost:$SVC_PORT/health" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 0.5
done
elapsed=$(( $(date +%s) - start ))
if [[ -z "$healthy" ]]; then
  echo "R-DEL-09 FAIL: service not healthy within 60 s" >&2
  docker logs "$SVC" 2>&1 | tail -40 >&2
  exit 1
fi
echo "R-DEL-09 measurement: start to first healthy /health = ${elapsed}s (limit 60 s)" >&2

"$HERE/run.sh" --base-url "http://localhost:$SVC_PORT" --mock-url "http://localhost:$MOCK_PORT" "$@"
