/**
 * Tests for the restaurant proxy server.
 * Uses Node's built-in test runner (node --test).
 */
const { test } = require('node:test');
const assert = require('node:assert');
const http = require('node:http');

// Import the Express app without starting the listener
const app = require('../server');

/**
 * Helper: make a GET request to the local test server.
 */
function request(server, path) {
  return new Promise((resolve, reject) => {
    const addr = server.address();
    const options = {
      hostname: '127.0.0.1',
      port: addr.port,
      path,
      method: 'GET',
    };

    const req = http.request(options, (res) => {
      let body = '';
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => resolve({ statusCode: res.statusCode, headers: res.headers, body }));
    });

    req.on('error', reject);
    req.end();
  });
}

test('CORS headers are present on /api/restaurants', async (t) => {
  const server = http.createServer(app).listen(0);
  t.after(() => server.close());

  const { headers } = await request(server, '/api/restaurants');

  // The CORS middleware must set Access-Control-Allow-Origin
  assert.ok(
    headers['access-control-allow-origin'],
    'Expected Access-Control-Allow-Origin header to be set',
  );
  assert.strictEqual(
    headers['access-control-allow-origin'],
    '*',
    'Expected Access-Control-Allow-Origin to be "*"',
  );
});

test('OPTIONS pre-flight on /api/restaurants returns 204', async (t) => {
  const server = http.createServer(app).listen(0);
  t.after(() => server.close());

  const addr = server.address();
  const { statusCode, headers } = await new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: addr.port,
        path: '/api/restaurants',
        method: 'OPTIONS',
        headers: {
          Origin: 'http://example.com',
          'Access-Control-Request-Method': 'GET',
        },
      },
      (res) => {
        let body = '';
        res.on('data', (c) => (body += c));
        res.on('end', () =>
          resolve({ statusCode: res.statusCode, headers: res.headers, body }),
        );
      },
    );
    req.on('error', reject);
    req.end();
  });

  assert.ok(
    [200, 204].includes(statusCode),
    `Pre-flight should return 200 or 204, got ${statusCode}`,
  );
  assert.ok(
    headers['access-control-allow-origin'],
    'Pre-flight should include Access-Control-Allow-Origin header',
  );
});

test('/health endpoint returns 200 with ok status', async (t) => {
  const server = http.createServer(app).listen(0);
  t.after(() => server.close());

  const { statusCode, body } = await request(server, '/health');

  assert.strictEqual(statusCode, 200);
  const json = JSON.parse(body);
  assert.strictEqual(json.status, 'ok');
});

test('/api/restaurants returns 502 when upstream is unavailable', async (t) => {
  // Point RESTAURANTS_API_URL at an unreachable host
  const original = process.env.RESTAURANTS_API_URL;
  process.env.RESTAURANTS_API_URL = 'http://127.0.0.1:1'; // guaranteed to fail

  const server = http.createServer(app).listen(0);
  t.after(() => {
    server.close();
    if (original === undefined) {
      delete process.env.RESTAURANTS_API_URL;
    } else {
      process.env.RESTAURANTS_API_URL = original;
    }
  });

  const { statusCode, body } = await request(server, '/api/restaurants');

  assert.strictEqual(statusCode, 502);
  const json = JSON.parse(body);
  assert.ok(json.error, 'Expected an error field in the response body');
});
