const express = require('express');
const cors = require('cors');
const fetch = require('node-fetch');
const path = require('path');

const app = express();
const PORT = process.env.PORT || 3000;

// CORS configuration — allow all origins so the browser client can reach this proxy
const corsOptions = {
  origin: '*',
  methods: ['GET', 'POST', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
};

app.use(cors(corsOptions));

// Handle pre-flight OPTIONS requests
app.options('*', cors(corsOptions));

// Serve the frontend
app.use(express.static(path.join(__dirname, 'public')));

// Proxy endpoint: fetch restaurants from an upstream API and relay the response
app.get('/api/restaurants', async (req, res) => {
  const upstreamUrl =
    process.env.RESTAURANTS_API_URL ||
    'https://restaurant-api.example.com/restaurants';

  console.log(`Fetching restaurants from proxy...`);
  console.log(`Upstream URL: ${upstreamUrl}`);

  try {
    const query = new URLSearchParams(req.query).toString();
    const targetUrl = query ? `${upstreamUrl}?${query}` : upstreamUrl;

    const response = await fetch(targetUrl, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error(
        `Upstream API error: ${response.status} ${response.statusText}`,
      );
      return res.status(response.status).json({
        error: `Upstream API returned ${response.status}`,
        details: errorText,
      });
    }

    const data = await response.json();
    console.log(`✅ Successfully fetched ${data.length ?? 1} restaurant(s).`);
    res.json(data);
  } catch (err) {
    console.error(`❌ Restaurant fetch error: ${err.message}`);
    res.status(502).json({
      error: 'Failed to fetch restaurants from the upstream API.',
      details: err.message,
    });
  }
});

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Proxy server running on http://localhost:${PORT}`);
  });
}

module.exports = app;
