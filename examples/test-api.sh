#!/bin/bash

# IoT Meter - API Test Script
# This script demonstrates all API endpoints

API_BASE="http://localhost:8080"

echo "=========================================="
echo "IoT Meter API Test Script"
echo "=========================================="
echo ""

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper function to print section headers
print_header() {
    echo ""
    echo -e "${BLUE}=== $1 ===${NC}"
    echo ""
}

# Helper function to print success
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Check if jq is available for pretty printing
if command -v jq &> /dev/null; then
    PRETTY="jq ."
else
    PRETTY="cat"
fi

# Test 1: Health Check
print_header "1. Health Check"
curl -s "$API_BASE/health" | $PRETTY
print_success "Health check complete"

# Test 2: Get All Devices
print_header "2. Get All Devices"
curl -s "$API_BASE/api/devices" | $PRETTY
print_success "Retrieved all devices"

# Test 3: Get Single Device
print_header "3. Get Single Device (device-001)"
curl -s "$API_BASE/api/devices/device-001" | $PRETTY
print_success "Retrieved device-001"

# Test 4: Create New Device
print_header "4. Create New Device"
curl -s -X POST "$API_BASE/api/devices" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "device-test-001",
    "device_name": "Test Temperature Sensor",
    "device_type": "temperature",
    "location": "Test Lab Room 1",
    "status": "active",
    "metadata": {
      "sampling_rate": "5s",
      "unit": "celsius",
      "range": {"min": -40, "max": 125}
    }
  }' | $PRETTY
print_success "Created new device"

# Test 5: Update Device
print_header "5. Update Device"
curl -s -X PUT "$API_BASE/api/devices/device-test-001" \
  -H "Content-Type: application/json" \
  -d '{
    "device_name": "Updated Test Sensor",
    "location": "Test Lab Room 2"
  }' | $PRETTY
print_success "Updated device"

# Test 6: Device Heartbeat
print_header "6. Send Device Heartbeat"
curl -s -X POST "$API_BASE/api/devices/device-001/heartbeat" | $PRETTY
print_success "Heartbeat sent"

# Test 7: Get Device Metrics
print_header "7. Get Device Metrics (last hour)"
curl -s "$API_BASE/api/devices/device-001/metrics?start=-1h" | $PRETTY
print_success "Retrieved metrics"

# Test 8: Get Device Raw Data Files
print_header "8. Get Device Raw Data Files"
curl -s "$API_BASE/api/devices/device-001/raw-data" | $PRETTY
print_success "Retrieved raw data file list"

# Test 9: Create Alert
print_header "9. Create Alert"
curl -s -X POST "$API_BASE/api/devices/device-001/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "alert_type": "high_temperature",
    "severity": "warning",
    "message": "Temperature exceeded 30°C threshold"
  }' | $PRETTY
print_success "Created alert"

# Test 10: Get Device Alerts
print_header "10. Get Device Alerts"
curl -s "$API_BASE/api/devices/device-001/alerts" | $PRETTY
print_success "Retrieved alerts"

# Test 11: Get System Statistics
print_header "11. Get System Statistics"
curl -s "$API_BASE/api/stats" | $PRETTY
print_success "Retrieved system statistics"

# Test 12: Filter Devices by Status
print_header "12. Filter Devices by Status (active)"
curl -s "$API_BASE/api/devices?status=active" | $PRETTY
print_success "Retrieved active devices"

# Test 13: Filter Devices by Type
print_header "13. Filter Devices by Type (temperature)"
curl -s "$API_BASE/api/devices?type=temperature" | $PRETTY
print_success "Retrieved temperature devices"

# Test 14: Delete Device
print_header "14. Delete Test Device"
curl -s -X DELETE "$API_BASE/api/devices/device-test-001" | $PRETTY
print_success "Deleted test device"

echo ""
echo "=========================================="
echo "All API tests completed!"
echo "=========================================="
echo ""
