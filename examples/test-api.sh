#!/bin/bash
# IoT Meter — API Test Script (v2)
# Demonstrates all REST API endpoints with correct v2 device types.

API_BASE="http://localhost:8080"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

header() { echo -e "\n${BLUE}=== $1 ===${NC}\n"; }
ok()     { echo -e "${GREEN}✓ $1${NC}"; }

if command -v jq &>/dev/null; then PRETTY="jq ."; else PRETTY="cat"; fi

# 1. Health Check
header "1. Health Check"
curl -s "$API_BASE/health" | $PRETTY
ok "Health check complete"

# 2. Get All Devices
header "2. Get All Devices"
curl -s "$API_BASE/api/devices" | $PRETTY
ok "Retrieved all devices"

# 3. Get Single Device (seeded DC meter)
header "3. Get Single Device (dc-meter-001)"
curl -s "$API_BASE/api/devices/dc-meter-001" | $PRETTY
ok "Retrieved dc-meter-001"

# 4. Create New Device
header "4. Create New Device (power_meter_dc)"
curl -s -X POST "$API_BASE/api/devices" \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "dc-meter-test-001",
    "name": "Test DC Power Meter",
    "type": "power_meter_dc",
    "location": "Test Lab — Bay 1",
    "status": "active",
    "metadata": {
      "sampling_rate": "5s",
      "voltage_range": {"min": 0, "max": 1000},
      "current_range": {"min": 0, "max": 500}
    }
  }' | $PRETTY
ok "Created device"

# 5. Update Device
header "5. Update Device"
curl -s -X PUT "$API_BASE/api/devices/dc-meter-test-001" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Test DC Meter",
    "location": "Test Lab — Bay 2"
  }' | $PRETTY
ok "Updated device"

# 6. Device Heartbeat
header "6. Send Device Heartbeat"
curl -s -X POST "$API_BASE/api/devices/dc-meter-001/heartbeat" | $PRETTY
ok "Heartbeat sent"

# 7. Get Device Measurements
header "7. Get Device Measurements (last hour)"
curl -s "$API_BASE/api/devices/dc-meter-001/measurements?hours=1" | $PRETTY
ok "Retrieved measurements"

# 8. Get Device Raw Data Files
header "8. Get Device Raw Data Files"
curl -s "$API_BASE/api/devices/dc-meter-001/raw-data" | $PRETTY
ok "Retrieved raw data files"

# 9. Create Alert
header "9. Create Alert"
curl -s -X POST "$API_BASE/api/devices/dc-meter-001/alerts" \
  -H "Content-Type: application/json" \
  -d '{
    "alert_type": "high_voltage",
    "severity": "warning",
    "message": "DC voltage exceeded 850V threshold"
  }' | $PRETTY
ok "Created alert"

# 10. Get Device Alerts
header "10. Get Device Alerts"
curl -s "$API_BASE/api/devices/dc-meter-001/alerts" | $PRETTY
ok "Retrieved alerts"

# 11. Send MQTT Command
header "11. Send MQTT Command"
curl -s -X POST "$API_BASE/api/devices/dc-meter-test-001/command" \
  -H "Content-Type: application/json" \
  -d '{"command": "reset", "params": {}}' | $PRETTY
ok "Command sent"

# 12. Get System Statistics
header "12. Get System Statistics"
curl -s "$API_BASE/api/stats" | $PRETTY
ok "Retrieved statistics"

# 13. Filter Devices by Status
header "13. Filter Devices by Status (active)"
curl -s "$API_BASE/api/devices?status=active" | $PRETTY
ok "Retrieved active devices"

# 14. Filter Devices by Type
header "14. Filter Devices by Type (power_meter_dc)"
curl -s "$API_BASE/api/devices?type=power_meter_dc" | $PRETTY
ok "Retrieved DC meters"

# 15. Delete Test Device
header "15. Delete Test Device"
curl -s -X DELETE "$API_BASE/api/devices/dc-meter-test-001" | $PRETTY
ok "Deleted test device"

echo ""
echo "=========================================="
echo "All API tests completed!"
echo "=========================================="
