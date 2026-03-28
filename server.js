'use strict';

const express = require('express');
const cors = require('cors');
const fetch = require('node-fetch');

const app = express();
const PORT = process.env.PORT || 3000;

// The upstream restaurant API URL (can be overridden via environment variable)
const RESTAURANT_API_URL =
  process.env.RESTAURANT_API_URL ||
  'https://www.zomato.com/webroutes/getPage?page_url=/bangalore/restaurants&location=&isMobile=1';

// Enable CORS for all routes and origins
app.use(cors());

// Parse JSON bodies
app.use(express.json());

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', message: 'Proxy server is running' });
});

// Proxy endpoint: fetches restaurant data from the upstream API
// and forwards it to the client, bypassing browser CORS restrictions.
app.get('/restaurants', async (req, res) => {
  console.log('Fetching restaurants from proxy...');
  try {
    const apiUrl = RESTAURANT_API_URL;

    const response = await fetch(apiUrl, {
      headers: {
        'User-Agent':
          'Mozilla/5.0 (compatible; Kutumbaba Proxy/1.0)',
        Accept: 'application/json, text/plain, */*',
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`Upstream API error ${response.status}: ${errorText}`);
      return res
        .status(response.status)
        .json({ error: `Upstream API returned ${response.status}` });
    }

    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const data = await response.json();
      return res.json(data);
    }

    const text = await response.text();
    return res.type(contentType || 'text/plain').send(text);
  } catch (err) {
    console.error('Restaurant fetch error:', err.message);
    return res.status(502).json({
      error: 'Failed to fetch restaurants from upstream API',
      details: err.message,
    });
  }
});

// Start the server
const server = app.listen(PORT, () => {
  console.log(`Proxy server listening on http://localhost:${PORT}`);
  console.log(`Fetch restaurants via: http://localhost:${PORT}/restaurants`);
});

module.exports = { app, server };
