/**
 * k6 Load Test — IoT Meter Device Manager API
 *
 * Tests all REST API endpoints under load with ramping virtual users.
 * Measures latency (p95, p99), throughput, and error rates.
 *
 * Usage:
 *   k6 run tests/performance/api_load_test.js
 *   k6 run -e BASE_URL=https://iot.bartok.sk tests/performance/api_load_test.js
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

export const options = {
  stages: [
    { duration: '30s', target: 10 },  // Ramp up to 10 VUs
    { duration: '1m',  target: 10 },  // Stay at 10 VUs
    { duration: '30s', target: 30 },  // Spike to 30 VUs
    { duration: '30s', target: 0 },   // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    http_req_failed: ['rate<0.01'],
    healthz_duration: ['p(95)<100'],
    readyz_duration: ['p(95)<200'],
    list_devices_duration: ['p(95)<300'],
    get_device_duration: ['p(95)<300'],
    create_device_duration: ['p(95)<500'],
    get_metrics_duration: ['p(95)<800'],
    get_stats_duration: ['p(95)<500'],
  },
};

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const healthzDuration      = new Trend('healthz_duration', true);
const readyzDuration       = new Trend('readyz_duration', true);
const listDevicesDuration  = new Trend('list_devices_duration', true);
const getDeviceDuration    = new Trend('get_device_duration', true);
const createDeviceDuration = new Trend('create_device_duration', true);
const getMetricsDuration   = new Trend('get_metrics_duration', true);
const getStatsDuration     = new Trend('get_stats_duration', true);
const heartbeatDuration    = new Trend('heartbeat_duration', true);
const deviceCreated        = new Counter('devices_created');
const deviceDeleted        = new Counter('devices_deleted');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const jsonHeaders = { headers: { 'Content-Type': 'application/json' } };

function uniqueDeviceId() {
  return `perf-test-${__VU}-${__ITER}-${Date.now()}`;
}

// Known seed devices from init-db.sql
const SEED_DEVICES = ['dc-meter-001', 'dc-meter-002', 'ac-meter-001'];

// ---------------------------------------------------------------------------
// Main scenario
// ---------------------------------------------------------------------------

export default function () {
  // ── Health probes ──────────────────────────────────────────────────────
  group('Health Probes', () => {
    const healthz = http.get(`${BASE_URL}/healthz`);
    healthzDuration.add(healthz.timings.duration);
    check(healthz, {
      'healthz returns 200': (r) => r.status === 200,
      'healthz body has alive': (r) => r.json().status === 'alive',
    });

    const readyz = http.get(`${BASE_URL}/readyz`);
    readyzDuration.add(readyz.timings.duration);
    check(readyz, {
      'readyz returns 200': (r) => r.status === 200,
      'readyz body has ready': (r) => r.json().status === 'ready',
    });
  });

  // ── List devices ───────────────────────────────────────────────────────
  group('List Devices', () => {
    const res = http.get(`${BASE_URL}/api/devices`);
    listDevicesDuration.add(res.timings.duration);
    check(res, {
      'list devices 200': (r) => r.status === 200,
      'list devices returns array': (r) => Array.isArray(r.json()),
    });
  });

  // ── Get single device ─────────────────────────────────────────────────
  group('Get Single Device', () => {
    const deviceId = SEED_DEVICES[Math.floor(Math.random() * SEED_DEVICES.length)];
    const res = http.get(`${BASE_URL}/api/devices/${deviceId}`);
    getDeviceDuration.add(res.timings.duration);
    check(res, {
      'get device 200': (r) => r.status === 200,
      'get device has device_id': (r) => r.json().device_id === deviceId,
    });
  });

  // ── Create + Delete device ─────────────────────────────────────────────
  group('Create & Delete Device', () => {
    const deviceId = uniqueDeviceId();

    const createRes = http.post(
      `${BASE_URL}/api/devices`,
      JSON.stringify({
        device_id: deviceId,
        device_name: `Perf Test Device ${deviceId}`,
        device_type: 'power_meter_dc',
        location: 'k6 load test',
      }),
      jsonHeaders,
    );
    createDeviceDuration.add(createRes.timings.duration);
    check(createRes, {
      'create device 201': (r) => r.status === 201,
    });

    if (createRes.status === 201) {
      deviceCreated.add(1);

      // Delete the device we just created to keep the DB clean
      const delRes = http.del(`${BASE_URL}/api/devices/${deviceId}`);
      check(delRes, {
        'delete device 200': (r) => r.status === 200,
      });
      if (delRes.status === 200) {
        deviceDeleted.add(1);
      }
    }
  });

  // ── Heartbeat ──────────────────────────────────────────────────────────
  group('Heartbeat', () => {
    const deviceId = SEED_DEVICES[0];
    const res = http.post(`${BASE_URL}/api/devices/${deviceId}/heartbeat`);
    heartbeatDuration.add(res.timings.duration);
    check(res, {
      'heartbeat 200': (r) => r.status === 200,
    });
  });

  // ── Get metrics (InfluxDB) ─────────────────────────────────────────────
  group('Get Metrics', () => {
    const deviceId = SEED_DEVICES[0];
    const res = http.get(`${BASE_URL}/api/devices/${deviceId}/metrics?start=-1h`);
    getMetricsDuration.add(res.timings.duration);
    check(res, {
      'get metrics 200': (r) => r.status === 200,
      'get metrics returns array': (r) => Array.isArray(r.json()),
    });
  });

  // ── System stats ───────────────────────────────────────────────────────
  group('System Stats', () => {
    const res = http.get(`${BASE_URL}/api/stats`);
    getStatsDuration.add(res.timings.duration);
    check(res, {
      'stats 200': (r) => r.status === 200,
    });
  });

  sleep(1); // Pace between iterations
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

export function handleSummary(data) {
  console.log('\n══════════════════════════════════════════════════════════');
  console.log('  IoT Meter — API Load Test Summary');
  console.log('══════════════════════════════════════════════════════════\n');

  const metrics = [
    ['healthz (p95)',       data.metrics.healthz_duration?.values?.['p(95)']],
    ['readyz (p95)',        data.metrics.readyz_duration?.values?.['p(95)']],
    ['list devices (p95)',  data.metrics.list_devices_duration?.values?.['p(95)']],
    ['get device (p95)',    data.metrics.get_device_duration?.values?.['p(95)']],
    ['create device (p95)', data.metrics.create_device_duration?.values?.['p(95)']],
    ['get metrics (p95)',   data.metrics.get_metrics_duration?.values?.['p(95)']],
    ['get stats (p95)',     data.metrics.get_stats_duration?.values?.['p(95)']],
    ['heartbeat (p95)',     data.metrics.heartbeat_duration?.values?.['p(95)']],
  ];

  metrics.forEach(([name, val]) => {
    if (val !== undefined) {
      console.log(`  ${name.padEnd(25)} ${val.toFixed(2)} ms`);
    }
  });

  console.log(`\n  Devices created: ${data.metrics.devices_created?.values?.count || 0}`);
  console.log(`  Devices deleted: ${data.metrics.devices_deleted?.values?.count || 0}`);
  console.log('');

  return {};
}
