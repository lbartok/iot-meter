#!/usr/bin/env bash
# =============================================================================
# start.sh — Bootstrap IoT Meter on Kubernetes and run the test suite
# =============================================================================
# Usage:
#   ./start.sh              # full flow: build → deploy → wait → test
#   ./start.sh --skip-build # deploy without rebuilding images
#   ./start.sh --tests-only # only run the test suite (cluster already up)
# =============================================================================

set -euo pipefail

# ---- Configuration ----------------------------------------------------------
REGISTRY="${REGISTRY:-iot-meter}"
NAMESPACE="${NAMESPACE:-iot-meter}"
TIMEOUT="${TIMEOUT:-180}"          # seconds to wait for pods
API_PORT="${API_PORT:-8080}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- Helpers ----------------------------------------------------------------
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites…"
    command -v docker  >/dev/null 2>&1 || fail "docker not found"
    command -v kubectl >/dev/null 2>&1 || fail "kubectl not found"
    kubectl cluster-info >/dev/null 2>&1 || fail "kubectl cannot reach a cluster"
    ok "Prerequisites satisfied"
}

# ---- Step 1: Build Docker images --------------------------------------------
build_images() {
    info "Building Docker images…"
    docker build -t "${REGISTRY}/device-manager:latest"         ./services/device-manager
    docker build -t "${REGISTRY}/mqtt-collector:latest"         ./services/mqtt-collector
    docker build -t "${REGISTRY}/iot-device-simulator:latest"   ./services/iot-device-simulator
    docker build -t "${REGISTRY}/alertmanager-github-receiver:latest" ./services/alertmanager-github-receiver
    ok "All images built"
}

# ---- Step 2: Deploy to Kubernetes -------------------------------------------
deploy() {
    info "Deploying to Kubernetes (namespace: ${NAMESPACE})…"
    kubectl apply -k k8s/base/
    ok "Manifests applied"
}

# ---- Step 3: Wait for pods --------------------------------------------------
wait_for_pods() {
    info "Waiting for all pods in namespace '${NAMESPACE}' to become Ready (timeout: ${TIMEOUT}s)…"

    local deadline=$(( $(date +%s) + TIMEOUT ))

    while true; do
        # Count not-ready pods (skip header line)
        local not_ready
        not_ready=$(kubectl get pods -n "${NAMESPACE}" --no-headers 2>/dev/null \
            | grep -v -E '([0-9]+)/\1\s+Running|Completed' | wc -l | tr -d ' ')

        if [[ "${not_ready}" -eq 0 ]]; then
            ok "All pods are Running and Ready"
            kubectl get pods -n "${NAMESPACE}"
            echo ""
            return 0
        fi

        if [[ $(date +%s) -ge ${deadline} ]]; then
            warn "Timeout reached. Current pod status:"
            kubectl get pods -n "${NAMESPACE}"
            fail "Not all pods became ready within ${TIMEOUT}s"
        fi

        sleep 5
    done
}

# ---- Step 4: Port-forward (background) --------------------------------------
start_port_forward() {
    info "Port-forwarding device-manager to localhost:${API_PORT}…"
    kubectl port-forward svc/device-manager "${API_PORT}:8080" -n "${NAMESPACE}" >/dev/null 2>&1 &
    PF_PID=$!
    # Give it a moment to establish
    sleep 3
    if ! kill -0 "${PF_PID}" 2>/dev/null; then
        fail "Port-forward process died unexpectedly"
    fi
    ok "Port-forward active (PID ${PF_PID})"
}

stop_port_forward() {
    if [[ -n "${PF_PID:-}" ]] && kill -0 "${PF_PID}" 2>/dev/null; then
        kill "${PF_PID}" 2>/dev/null || true
        info "Port-forward stopped"
    fi
}

# ---- Step 5: Run tests ------------------------------------------------------
run_tests() {
    info "Installing test dependencies…"
    pip install -q -r requirements-test.txt

    echo ""
    info "Running unit tests…"
    python -m pytest tests/unit -v --tb=short || true

    echo ""
    info "Running integration tests…"
    python -m pytest tests/integration -v --tb=short || true

    echo ""
    info "Running e2e tests…"
    python -m pytest tests/e2e -v --tb=short -m e2e || true

    echo ""
    info "Running full suite with coverage…"
    python -m pytest tests/unit tests/integration -v --tb=short \
        --cov=services --cov-report=term-missing || true

    ok "Test run complete"
}

# ---- Main -------------------------------------------------------------------
main() {
    local skip_build=false
    local tests_only=false

    for arg in "$@"; do
        case "${arg}" in
            --skip-build)  skip_build=true ;;
            --tests-only)  tests_only=true ;;
            -h|--help)
                echo "Usage: $0 [--skip-build] [--tests-only]"
                exit 0
                ;;
        esac
    done

    echo ""
    echo "=============================================="
    echo "  IoT Meter — Kubernetes Bootstrap & Tests"
    echo "=============================================="
    echo ""

    if ${tests_only}; then
        run_tests
        exit 0
    fi

    check_prerequisites

    if ! ${skip_build}; then
        build_images
    fi

    deploy
    wait_for_pods

    start_port_forward
    trap stop_port_forward EXIT

    run_tests

    echo ""
    ok "All done! The cluster is still running."
    echo ""
    echo "  Useful commands:"
    echo "    make k8s-status        — check pod status"
    echo "    make k8s-port-forward  — re-open port-forward"
    echo "    make k8s-logs-manager  — view Device Manager logs"
    echo "    make k8s-delete        — tear down the deployment"
    echo ""
}

main "$@"
