// Zero-dependency static file server for the Jarvis web app.
// Jarvis is a fully client-side app: it talks to Google Gemini directly from the
// browser using the user's own API key, so this server only serves static assets.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync, statSync } from 'node:fs';
import path from 'node:path';
import url from 'node:url';

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 3000;

const CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json',
};

function sendError(res, code, message) {
  res.writeHead(code, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end(message);
}

export const server = http.createServer(async (req, res) => {
  try {
    const requestPath = decodeURIComponent(
      new URL(req.url, 'http://localhost').pathname,
    );

    // Lightweight health check for infra/monitoring.
    if (requestPath === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
      res.end(JSON.stringify({ status: 'ok', app: 'jarvis' }));
      return;
    }

    let relative = requestPath === '/' ? '/index.html' : requestPath;
    let filePath = path.join(PUBLIC_DIR, path.normalize(relative));

    // Prevent path traversal outside the public directory.
    if (!filePath.startsWith(PUBLIC_DIR)) {
      return sendError(res, 403, 'Forbidden');
    }

    // Fall back to index.html for unknown, extension-less routes (SPA behaviour).
    if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
      if (path.extname(filePath)) {
        return sendError(res, 404, 'Not found');
      }
      filePath = path.join(PUBLIC_DIR, 'index.html');
    }

    const data = await readFile(filePath);
    const ext = path.extname(filePath).toLowerCase();
    res.writeHead(200, {
      'Content-Type': CONTENT_TYPES[ext] || 'application/octet-stream',
      'Cache-Control': 'no-cache',
    });
    res.end(data);
  } catch (err) {
    sendError(res, 500, `Server error: ${err.message}`);
  }
});

if (process.env.NODE_ENV !== 'test') {
  server.listen(PORT, () => {
    console.log(`Jarvis is listening on http://localhost:${PORT}`);
  });
}
