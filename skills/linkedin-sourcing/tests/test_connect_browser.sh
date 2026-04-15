#!/bin/bash
# Tests for connect_browser.sh automatic auth behavior
#
# Run with: bash skills/linkedin-sourcing/tests/test_connect_browser.sh
#
# These tests verify:
# 1. --check-only and --status are hermetic (no browser launch)
# 2. Default invocation auto-bootstraps when no auth available
# 3. --no-bootstrap fails closed without browser launch
# 4. User is prompted to log in, not to launch Chrome

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONNECT_SCRIPT="$SCRIPT_DIR/../scripts/connect_browser.sh"

# Port is arbitrary since we mock curl to control CDP availability
TEST_PORT="29999"

# Isolate HOME so tests do not depend on ambient profile.sh or runtime state
TEST_HOME=$(mktemp -d)
export HOME="$TEST_HOME"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper: run test and check exit code
run_test() {
    local test_name="$1"
    local expected_exit="$2"
    shift 2
    local cmd="$@"

    echo -n "Testing: $test_name... "

    set +e
    eval "$cmd" >/dev/null 2>&1
    local actual_exit=$?
    set -e

    if [[ "$actual_exit" -eq "$expected_exit" ]]; then
        echo -e "${GREEN}PASS${NC} (exit $actual_exit)"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}FAIL${NC} (expected exit $expected_exit, got $actual_exit)"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Helper: check that output contains expected string
check_output_contains() {
    local test_name="$1"
    local expected="$2"
    shift 2
    local cmd="$@"

    echo -n "Testing: $test_name... "

    local output
    set +e
    output=$(eval "$cmd" 2>&1)
    local exit_code=$?
    set -e

    if echo "$output" | grep -q "$expected"; then
        echo -e "${GREEN}PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}FAIL${NC} (expected '$expected' in output)"
        echo "  Output: $output"
        ((TESTS_FAILED++))
        return 1
    fi
}

echo "=== connect_browser.sh Behavior Tests ==="
echo ""
echo "Note: These tests verify non-launching behavior."
echo "They do NOT require a running browser."
echo ""

# Create a mock curl that simulates 'no CDP available' for hermetic tests
mock_cdp_unavailable_dir=$(mktemp -d)
cat > "$mock_cdp_unavailable_dir/curl" <<'EOF'
#!/bin/bash
# Mock curl that always fails (simulates no CDP browser available)
exit 1
EOF
chmod +x "$mock_cdp_unavailable_dir/curl"

# Test 1: --check-only with no browser should exit 1 (hermetic)
run_test "--check-only fails closed when no CDP" 1 "PATH=\"$mock_cdp_unavailable_dir:\$PATH\" bash \"$CONNECT_SCRIPT\" --check-only --port $TEST_PORT"

# Test 2: --status with no browser should exit 1 (hermetic)
run_test "--status fails closed when no CDP" 1 "PATH=\"$mock_cdp_unavailable_dir:\$PATH\" bash \"$CONNECT_SCRIPT\" --status --port $TEST_PORT"

# Test 3: Default invocation with no browser should exit 1 (non-launching)
run_test "Default invocation fails closed when no CDP" 1 "PATH=\"$mock_cdp_unavailable_dir:\$PATH\" bash \"$CONNECT_SCRIPT\" --port $TEST_PORT"

# Prepare a mocked python3 so bootstrap-path tests stay hermetic
mock_bootstrap_dir=$(mktemp -d)
cat > "$mock_bootstrap_dir/python3" <<'EOF'
#!/bin/bash
if [[ "$1" == *"auth_bootstrap.py"* ]]; then
  printf '%s\n' '{"success": true, "mode": "cdp", "cdp_port": "29999", "session_name": null, "auth_file": null, "message": "mock bootstrap", "error": null}'
else
  /usr/bin/python3 "$@"
fi
EOF
chmod +x "$mock_bootstrap_dir/python3"

# Isolated work dir so bootstrap-path tests do not depend on ambient runtime state
mock_bootstrap_work_dir=$(mktemp -d)

# Test 4: Default invocation (with auto-bootstrap) routes into bootstrap flow
echo -n "Testing: Default invocation uses bootstrap flow hermetically... "
output=$(WORK_DIR="$mock_bootstrap_work_dir" PATH="$mock_bootstrap_dir:$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -q "CONNECTED"; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC} (bootstrap flow was not reached)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
fi

# Test 5: --status outputs valid JSON
echo -n "Testing: --status outputs valid JSON... "
output=$(PATH="$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --status --port $TEST_PORT 2>&1) || true
if echo "$output" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC} (invalid JSON)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
fi

# Test 6: --status JSON contains expected fields
echo -n "Testing: --status JSON has required fields... "
output=$(PATH="$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --status --port $TEST_PORT 2>&1) || true
if echo "$output" | python3 -c "
import sys, json
data = json.load(sys.stdin)
required = ['status', 'mode', 'cdp_port', 'authenticated', 'message', 'error']
missing = [f for f in required if f not in data]
if missing:
    print(f'Missing fields: {missing}')
    sys.exit(1)
" 2>/dev/null; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC} (missing required fields)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
fi

# Test 7: --no-bootstrap fails closed with guidance
echo -n "Testing: --no-bootstrap fails closed with guidance... "
output=$(PATH="$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --no-bootstrap --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -q "\-\-no-bootstrap"; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC} (missing --no-bootstrap guidance)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
fi

# Test 7b: No manual Chrome launch guidance in error messages
echo -n "Testing: No manual Chrome launch guidance in errors... "
output=$(PATH="$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --no-bootstrap --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -q "remote-debugging-port"; then
    echo -e "${RED}FAIL${NC} (should not suggest manual Chrome launch)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
else
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
fi

# Test 8: --no-bootstrap flag is recognized (doesn't show "Unknown option")
echo -n "Testing: --no-bootstrap flag is recognized... "
output=$(PATH="$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --no-bootstrap --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -q "Unknown option"; then
    echo -e "${RED}FAIL${NC} (--no-bootstrap not recognized)"
    ((TESTS_FAILED++))
else
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
fi

# Test 8b: --bootstrap flag is still recognized for backward compatibility
echo -n "Testing: --bootstrap flag is recognized (backward compat)... "
output=$(WORK_DIR="$mock_bootstrap_work_dir" PATH="$mock_bootstrap_dir:$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --bootstrap --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -q "Unknown option"; then
    echo -e "${RED}FAIL${NC} (--bootstrap not recognized)"
    ((TESTS_FAILED++))
else
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
fi

# Test 9: --check-only on authenticated fast path does not write runtime state
echo -n "Testing: --check-only authenticated path is read-only... "
mock_dir=$(mktemp -d)
mock_work_dir=$(mktemp -d)
cat > "$mock_dir/curl" <<'EOF'
#!/bin/bash
exit 0
EOF
cat > "$mock_dir/python3" <<'EOF'
#!/bin/bash
if [[ "$*" == *"from browser_utils import probe_recruiter_auth"* ]]; then
  printf '%s\n' '{"authenticated": true, "url": "https://www.linkedin.com/talent/home"}'
elif [[ "$*" == *"json.load(sys.stdin).get('authenticated'"* ]]; then
  printf '%s\n' 'True'
else
  /usr/bin/python3 "$@"
fi
EOF
chmod +x "$mock_dir/curl" "$mock_dir/python3"

set +e
output=$(PATH="$mock_dir:$PATH" WORK_DIR="$mock_work_dir" bash "$CONNECT_SCRIPT" --check-only --port $TEST_PORT 2>&1)
exit_code=$?
set -e

if [[ "$exit_code" -eq 0 && ! -e "$mock_work_dir/runtime/browser_mode.json" ]]; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC} (exit $exit_code, browser mode file present=$( [[ -e "$mock_work_dir/runtime/browser_mode.json" ]] && echo yes || echo no ))"
    echo "  Output: $output"
    ((TESTS_FAILED++))
fi

# Test 10: Bootstrap mode explains the flow clearly (user logs in, not launches Chrome)
echo -n "Testing: Bootstrap message explains auto-flow... "
output=$(WORK_DIR="$mock_bootstrap_work_dir" PATH="$mock_bootstrap_dir:$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -q "Launching Chrome for LinkedIn Recruiter login"; then
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
else
    echo -e "${RED}FAIL${NC} (missing auto-flow explanation)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
fi

# Test 11: No 'launch Chrome manually' guidance in any output
echo -n "Testing: No 'launch Chrome manually' guidance... "
output=$(WORK_DIR="$mock_bootstrap_work_dir" PATH="$mock_bootstrap_dir:$mock_cdp_unavailable_dir:$PATH" bash "$CONNECT_SCRIPT" --port $TEST_PORT 2>&1) || true
if echo "$output" | grep -iq "launch Chrome manually"; then
    echo -e "${RED}FAIL${NC} (found manual launch guidance)"
    echo "  Output: $output"
    ((TESTS_FAILED++))
else
    echo -e "${GREEN}PASS${NC}"
    ((TESTS_PASSED++))
fi

rm -rf "$mock_dir" "$mock_work_dir"
rm -rf "$mock_bootstrap_dir"
rm -rf "$mock_bootstrap_work_dir"
rm -rf "$mock_cdp_unavailable_dir"
rm -rf "$TEST_HOME"

echo ""
echo "=== Test Summary ==="
echo -e "Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [[ "$TESTS_FAILED" -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
