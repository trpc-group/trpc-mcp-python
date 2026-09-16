#!/usr/bin/env bash
#
# Copyright @ 2025 Tencent.com
#
# Run the trpc-mcp client examples. For each example this script starts the
# matching MCP server, waits until it is listening, runs the client, then tears
# the server down again - so every example is independently runnable.
#
# Usage:
#   ./run_examples.sh                 # run all default (SSE) examples
#   ./run_examples.sh all             # same as above
#   ./run_examples.sh tool            # run a single example (tool/prompt/resource/...)
#   ./run_examples.sh tool <conf>     # run one example against a specific config (server + client)
#   ./run_examples.sh streamable      # run the core examples against streamable-http
#   ./run_examples.sh polaris         # run the polaris example (needs an external Polaris registry)
#   ./run_examples.sh list            # list available example names
#
# Available examples: tool prompt resource structured_output icons_meta roots selector mixed polaris
set -u

# pip3 install -r requirements.txt
# ---------------------------------------------------------------------------
# Paths / interpreter
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Prefer the project venv, fall back to python3 on PATH.
if [[ -x "${REPO_ROOT}/venv/bin/python" ]]; then
  PY="${REPO_ROOT}/venv/bin/python"
else
  PY="$(command -v python3)"
fi

SERVER_SCRIPT="${SCRIPT_DIR}/trpc_main.py"
SERVER_LOG="${SCRIPT_DIR}/.server_run.log"
SERVER_PID=""         # pid of the running server (for clean teardown)
HOST="127.0.0.1"
PORTS=(8008 8009)     # ports the example servers listen on (Greeter1 / Greeter2)

# ---------------------------------------------------------------------------
# Example table: name -> "client_script_relative_to_SCRIPT_DIR|default_conf_relative"
# ---------------------------------------------------------------------------
declare -A CLIENT=(
  [tool]="test_trpc_mcp_tool.py|trpc_python.yaml"
  [prompt]="test_mcp/test_trpc_mcp_prompt.py|trpc_python.yaml"
  [resource]="test_mcp/test_trpc_mcp_resource.py|trpc_python.yaml"
  [structured_output]="test_mcp/test_trpc_mcp_structured_output.py|trpc_python.yaml"
  [icons_meta]="test_mcp/test_trpc_mcp_icons_meta.py|trpc_python.yaml"
  [roots]="test_mcp/test_trpc_mcp_roots.py|trpc_python.yaml"
  [selector]="test_mcp/test_trpc_mcp_selector.py|conf/trpc_python_selector.yaml"
  [mixed]="test_mcp/test_trpc_mcp_mixed_protocol.py|conf/trpc_python_mixed.yaml"
  # [polaris]="test_mcp/test_trpc_mcp_polaris.py|conf/trpc_python_polaris.yaml"
)
# Examples run by "all" (polaris needs external infra, so it is opt-in only).
DEFAULT_ORDER=(tool prompt resource structured_output icons_meta roots selector mixed)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m[PASS]\033[0m %s\n' "$*"; }
bad() { printf '\033[1;31m[FAIL]\033[0m %s\n' "$*"; }

port_open() { (exec 3<>"/dev/tcp/${HOST}/$1") 2>/dev/null && exec 3>&- ; }

wait_ready() {
  # Wait until all PORTS accept connections, or time out.
  local tries=60
  while (( tries-- > 0 )); do
    local all=1
    for p in "${PORTS[@]}"; do
      port_open "$p" || all=0
    done
    [[ $all -eq 1 ]] && return 0
    # Bail out early if the server process already died.
    if [[ -n "${SERVER_PID}" ]] && ! kill -0 "${SERVER_PID}" 2>/dev/null; then
      return 1
    fi
    sleep 0.5
  done
  return 1
}

start_server() {
  local conf="$1"
  log "starting server: $(basename "${conf}")"
  : > "${SERVER_LOG}"
  # `exec` makes the subshell BECOME the python process, so $! is the real pid.
  ( cd "${SCRIPT_DIR}" && exec "${PY}" "${SERVER_SCRIPT}" --conf "${conf}" ) >>"${SERVER_LOG}" 2>&1 &
  SERVER_PID=$!
  if ! wait_ready; then
    bad "server failed to become ready; last log lines:"
    tail -n 30 "${SERVER_LOG}" || true
    stop_server
    return 1
  fi
  return 0
}

stop_server() {
  [[ -z "${SERVER_PID}" ]] && return 0
  # Kill worker child(ren) first, then the main process.
  pkill -TERM -P "${SERVER_PID}" 2>/dev/null || true
  kill -TERM "${SERVER_PID}" 2>/dev/null || true
  for _ in 1 2 3 4 5 6; do
    kill -0 "${SERVER_PID}" 2>/dev/null || break
    sleep 0.5
  done
  pkill -KILL -P "${SERVER_PID}" 2>/dev/null || true
  kill -KILL "${SERVER_PID}" 2>/dev/null || true
  # Wait for the listening ports to actually free up before the next case.
  for _ in 1 2 3 4 5 6 7 8; do
    port_open "${PORTS[0]}" || break
    sleep 0.5
  done
  SERVER_PID=""
}

run_case() {
  # run_case <name> [conf_override]
  local name="$1"
  local conf_override="${2:-}"
  local spec="${CLIENT[$name]:-}"
  if [[ -z "${spec}" ]]; then
    bad "unknown example: ${name} (try: ./run_examples.sh list)"
    return 2
  fi
  local script="${SCRIPT_DIR}/${spec%%|*}"
  local conf_rel="${conf_override:-${spec##*|}}"
  local conf="${SCRIPT_DIR}/${conf_rel}"
  if [[ ! -f "${conf}" ]]; then
    bad "${name}: config not found: ${conf}"
    return 2
  fi

  start_server "${conf}" || return 1

  log "running example: ${name} (${spec%%|*})"
  local rc=0
  # Guard against a hanging client so one example can't block the whole run.
  ( cd "${SCRIPT_DIR}" && timeout "${CLIENT_TIMEOUT:-90}" "${PY}" "${script}" --conf "${conf}" ) || rc=$?
  [[ ${rc} -eq 124 ]] && bad "${name}: client timed out after ${CLIENT_TIMEOUT:-90}s"

  stop_server

  if [[ ${rc} -eq 0 ]]; then
    ok "${name}"
  else
    bad "${name} (exit ${rc})"
  fi
  return ${rc}
}

# Always tear the server down, even on Ctrl-C / unexpected exit.
trap 'stop_server' EXIT INT TERM

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  local arg1="${1:-all}"

  case "${arg1}" in
    list)
      echo "Available examples: ${!CLIENT[*]}"
      echo "Default (all):      ${DEFAULT_ORDER[*]}"
      return 0
      ;;
    all)
      local failed=()
      for name in "${DEFAULT_ORDER[@]}"; do
        run_case "${name}" || failed+=("${name}")
      done
      echo
      if [[ ${#failed[@]} -eq 0 ]]; then
        ok "all examples passed: ${DEFAULT_ORDER[*]}"
        return 0
      fi
      bad "failed examples: ${failed[*]}"
      return 1
      ;;
    streamable)
      # Run the core examples against the streamable-http server.
      local conf="conf/trpc_python_streamable_http.yaml"
      local failed=()
      for name in tool prompt resource structured_output icons_meta roots; do
        run_case "${name}" "${conf}" || failed+=("${name}")
      done
      echo
      if [[ ${#failed[@]} -eq 0 ]]; then
        ok "all streamable-http examples passed"
        return 0
      fi
      bad "failed examples: ${failed[*]}"
      return 1
      ;;
    *)
      # Single example, optional conf override as $2.
      run_case "${arg1}" "${2:-}"
      return $?
      ;;
  esac
}

main "$@"
