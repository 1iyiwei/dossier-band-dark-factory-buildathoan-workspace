#!/usr/bin/env bash
# Run the stage-1 acceptance tests against an already-running service and mock web.
#
#   ./run.sh [--base-url URL] [--mock-url URL] [--mock-token TOKEN] [--old-url URL] [--old2-url URL] [--container NAME] [--no-corpus] [pytest args...]
#
# Defaults: service http://localhost:18001, mock http://localhost:18081, token local-admin.
# The mock must serve corpus/ from this folder unless --no-corpus is given (then the
# corpus-specific tests are skipped).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export BASE_URL="${BASE_URL:-http://localhost:18001}"
export MOCK_URL="${MOCK_URL:-http://localhost:18081}"
export MOCK_ADMIN_TOKEN="${MOCK_ADMIN_TOKEN:-local-admin}"
export ANALYST_CORPUS="${ANALYST_CORPUS:-1}"
export OLD_BASE_URL="${OLD_BASE_URL:-}"   # FINAL stage-1 service sharing the mock (upgrade tests)
export OLD2_BASE_URL="${OLD2_BASE_URL:-}"  # FINAL stage-2 service sharing the mock (upgrade tests)
export SVC_CONTAINER="${SVC_CONTAINER:-}"  # docker name of the service under test (restart tests)
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="$2"; shift 2 ;;
    --mock-url) MOCK_URL="$2"; shift 2 ;;
    --mock-token) MOCK_ADMIN_TOKEN="$2"; shift 2 ;;
    --old-url) OLD_BASE_URL="$2"; shift 2 ;;
    --old2-url) OLD2_BASE_URL="$2"; shift 2 ;;
    --container) SVC_CONTAINER="$2"; shift 2 ;;
    --no-corpus) ANALYST_CORPUS=0; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

pick_python() {
  if [[ -n "${PYTHON:-}" ]]; then echo "$PYTHON"; return; fi
  local kick="${KICKOFF:-$HERE/../../../../../sf-buildathon-2026}/.venv/bin/python"
  for p in "$kick" python3; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c "import pytest, httpx, playwright" 2>/dev/null; then
      echo "$p"; return
    fi
  done
  local venv="${TMPDIR:-/tmp}/dossier-acceptance-venv"
  if [[ ! -x "$venv/bin/python" ]]; then
    python3 -m venv "$venv" >&2
    "$venv/bin/pip" install -q -r "$HERE/requirements.txt" >&2
    "$venv/bin/playwright" install chromium >&2
  fi
  echo "$venv/bin/python"
}

PY="$(pick_python)"
echo "acceptance: service=$BASE_URL mock=$MOCK_URL corpus=$ANALYST_CORPUS python=$PY" >&2
cd "$HERE"
exec "$PY" -m pytest -p no:cacheprovider -rfEs "${ARGS[@]+"${ARGS[@]}"}"
