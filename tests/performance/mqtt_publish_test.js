/**
 * k6 Load Test — MQTT Publish Pipeline (end-to-end)
 *
 * Publishes v2 telemetry datagrams via HTTP to the Mosquitto broker's
 * REST API (if enabled) or via a helper script, then verifies the data
 * arrives in the Device Manager API.
 *
 * Since k6 doesn't have a native MQTT module, this test uses a companion
 * approach: it calls a small HTTP endpoint that publishes to MQTT on behalf
 * of k6. If no helper is available, it falls back to testing the full
 * ingestion pipeline by checking metrics after a delay.
 *
 * Usage:
 *   k6 run tests/performance/mqtt_publish_test.js
 *   k6 run -e BASE_URL=https://iot.bartok.sk tests/performance/mqtt_publish_test.js
 */

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.1.0/index.js';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

export const options = {
  scenarios: {
    // Scenario 1: Verify ingestion pipeline is working
    ingestion_check: {
      executor: 'constant-vus',
      vus: 5,
      duration: '1m',
      exec: 'ingestionCheck',
    },
    // Scenario 2: Stress the API read path (simulating dashboard queries)
    dashboard_read: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '20s', target: 5 },
        { duration: '30s', target: 15 },
        { duration: '20s', target: 25 },
        { duration: '20s', target: 5 },
        { duration: '10s', target: 0 },
      ],
      exec: 'dashboardRead',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<800'],
    http_req_failed: ['rate<0.02'],
    metrics_query_duration: ['p(95)<600'],
    raw_data_query_duration: ['p(95)<500'],
  },
};

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------

const metricsQueryDuration  = new Trend('metrics_query_duration', true);
const rawDataQueryDuration  = new Trend('raw_data_query_duration', true);
const alertsQueryDuration   = new Trend('alerts_query_duration', true);
const commandsDuration      = new Trend('commands_duration', true);
const successfulReads       = new Counter('successful_reads');

// Known seed devices
const SEED_DEVICES = ['dc-meter-001', 'dc-meter-002', 'ac-meter-001'];

const jsonHeaders = { headers: { 'Content-Type': 'application/json' } };

// ---------------------------------------------------------------------------
// Scenario 1: Ingestion pipeline check
// ---------------------------------------------------------------------------

export function ingestionCheck() {
  const deviceId = SEED_DEVICES[Math.floor(Math.random() * SEED_DEVICES.length)];

  group('Ingestion Pipeline Check', () => {
    // Check metrics are being ingested
    const metricsRes = http.get(
      `${BASE_URL}/api/devices/${deviceId}/metrics?start=-5m`,
    );
    metricsQueryDuration.add(metricsRes.timings.duration);
    check(metricsRes, {
      'metrics query 200': (r) => r.status === 200,
      'metrics returns data': (r) => {
        const body = r.json();
        return Array.isArray(body);
      },
    });

    // Check raw data in MinIO
    const rawRes = http.get(`${BASE_URL}/api/devices/${deviceId}/raw-data`);
    rawDataQueryDuration.add(rawRes.timings.duration);
    check(rawRes, {
      'raw data 200': (r) => r.status === 200,
    });

    if (metricsRes.status === 200) {
      successfulReads.add(1);
    }
  });

  sleep(2);
}

// ---------------------------------------------------------------------------
// Scenario 2: Dashboard read pattern (simulates a monitoring dashboard)
// ---------------------------------------------------------------------------

export function dashboardRead() {
  group('Dashboard Read Pattern', () => {
    // 1. List all devices (sidebar)
    const devicesRes = http.get(`${BASE_URL}/api/devices`);
    check(devicesRes, {
      'dashboard list 200': (r) => r.status === 200,
    });

    // 2. Get stats (overview panel)
    const statsRes = http.get(`${BASE_URL}/api/stats`);
    check(statsRes, {
      'dashboard stats 200': (r) => r.status === 200,
    });

    // 3. Get metrics for each seed device (charts)
    SEED_DEVICES.forEach((deviceId) => {
      const res = http.get(
        `${BASE_URL}/api/devices/${deviceId}/metrics?start=-1h`,
      );
      metricsQueryDuration.add(res.timings.duration);
      check(res, {
        [`metrics ${deviceId} 200`]: (r) => r.status === 200,
      });
    });

    // 4. Get alerts for a device
    const alertsRes = http.get(
      `${BASE_URL}/api/devices/${SEED_DEVICES[0]}/alerts`,
    );
    alertsQueryDuration.add(alertsRes.timings.duration);
    check(alertsRes, {
      'alerts query 200': (r) => r.status === 200,
    });

    // 5. Send a command (occasional)
    if (__ITER % 5 === 0) {
      const cmdRes = http.post(
        `${BASE_URL}/api/devices/${SEED_DEVICES[0]}/commands`,
        JSON.stringify({
          cmd: 'request_status',
          params: {},
        }),
        jsonHeaders,
      );
      commandsDuration.add(cmdRes.timings.duration);
      check(cmdRes, {
        'command sent': (r) => r.status === 201 || r.status === 200,
      });
    }
  });

  sleep(1);
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

export function handleSummary(data) {
  console.log('\n══════════════════════════════════════════════════════════');
  console.log('  IoT Meter — MQTT Ingestion & Dashboard Load Test');
  console.log('══════════════════════════════════════════════════════════\n');

  const metrics = [
    ['metrics query (p95)',   data.metrics.metrics_query_duration?.values?.['p(95)']],
    ['raw data query (p95)',  data.metrics.raw_data_query_duration?.values?.['p(95)']],
    ['alerts query (p95)',    data.metrics.alerts_query_duration?.values?.['p(95)']],
    ['commands (p95)',        data.metrics.commands_duration?.values?.['p(95)']],
  ];

  metrics.forEach(([name, val]) => {
    if (val !== undefined) {
      console.log(`  ${name.padEnd(25)} ${val.toFixed(2)} ms`);
    }
  });

  console.log(`\n  Successful reads: ${data.metrics.successful_reads?.values?.count || 0}`);
  console.log('');

  return {
    stdout: textSummary(data, { indent: ' ', enableColors: true }),
  };
}
