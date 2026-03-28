'use strict';

/**
 * Basic integration tests for the proxy server.
 * Run with: node test.js
 */

const fetch = require('node-fetch');
const { app, server } = require('./server');

let passed = 0;
let failed = 0;

async function test(name, fn) {
  try {
    await fn();
    console.log(`✅ PASS: ${name}`);
    passed++;
  } catch (err) {
    console.error(`❌ FAIL: ${name}`);
    console.error('   ', err.message);
    failed++;
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message || 'Assertion failed');
  }
}

async function fetchLocal(path) {
  return fetch(`http://localhost:3000${path}`);
}

(async () => {
  // Give the server a moment to start
  await new Promise((r) => setTimeout(r, 200));

  await test('GET /health returns 200 with status ok', async () => {
    const res = await fetchLocal('/health');
    assert(res.status === 200, `Expected 200 got ${res.status}`);
    const json = await res.json();
    assert(json.status === 'ok', `Expected status ok, got ${json.status}`);
  });

  await test('GET /health response has CORS header', async () => {
    const res = await fetchLocal('/health');
    const acao = res.headers.get('access-control-allow-origin');
    assert(acao !== null, 'Missing Access-Control-Allow-Origin header');
    assert(acao === '*', `Expected *, got ${acao}`);
  });

  await test('GET /restaurants returns 200 or 502 (upstream may be unavailable)', async () => {
    const res = await fetchLocal('/restaurants');
    const allowedStatuses = [200, 502, 403, 404];
    assert(
      allowedStatuses.includes(res.status),
      `Unexpected status ${res.status}`
    );
  });

  await test('GET /restaurants response has CORS header', async () => {
    const res = await fetchLocal('/restaurants');
    const acao = res.headers.get('access-control-allow-origin');
    assert(acao !== null, 'Missing Access-Control-Allow-Origin header on /restaurants');
    assert(acao === '*', `Expected *, got ${acao}`);
  });

  server.close();
  console.log(`\nResults: ${passed} passed, ${failed} failed`);
  process.exit(failed > 0 ? 1 : 0);
})();
