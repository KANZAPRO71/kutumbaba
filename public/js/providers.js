// Reply providers. Both expose the same async interface:
//   generateReply({ userText, snapshot, turns, extracted, now }) -> { reply, sources }
//
// GeminiProvider  -> live Google Gemini with Google Search grounding (sourced answers)
// DemoProvider    -> fully offline brain (used when no API key is configured)
import { mockReply } from './core/reply.js';
import { formatDay } from './core/datetime.js';

function buildContextBlock(snapshot) {
  const lines = [];
  const p = snapshot.profile || {};
  if (p.name) lines.push(`Name: ${p.name}`);
  if (p.location) lines.push(`Location: ${p.location}`);

  const mems = snapshot.memories || [];
  if (mems.length) {
    lines.push('What you remember about them:');
    mems.slice(-25).forEach((m) => lines.push(`- ${m.text}`));
  }

  const open = (snapshot.reminders || []).filter((r) => !r.done);
  if (open.length) {
    lines.push('Open follow-ups:');
    open.forEach((r) =>
      lines.push(`- ${r.text}${r.dueISO ? ` (due ${formatDay(r.dueISO)})` : ''}`),
    );
  }
  return lines.length ? lines.join('\n') : '(nothing remembered yet)';
}

export class DemoProvider {
  constructor() {
    this.mode = 'demo';
  }

  async generateReply({ userText, snapshot, extracted, now }) {
    // Small delay so the "thinking" state is visible, like a real call.
    await new Promise((r) => setTimeout(r, 250));
    return { reply: mockReply(userText, snapshot, extracted, now), sources: [] };
  }
}

export class GeminiProvider {
  constructor({ apiKey, model = 'gemini-2.0-flash' }) {
    this.apiKey = apiKey;
    this.model = model;
    this.mode = 'live';
  }

  systemPrompt(snapshot) {
    return [
      'You are Jarvis — a warm, concise, voice-first personal assistant.',
      'You talk naturally and briefly, the way you would speak out loud. Avoid long lists unless asked.',
      'You remember the user across every conversation and use that memory to be personal and proactive.',
      'When the user shares durable facts (names, dates, preferences, projects) or tasks, weave a short acknowledgement into your reply.',
      'For anything time-sensitive (weather, news, prices, facts), use Google Search and ground your answer in real sources.',
      '',
      'MEMORY & CONTEXT:',
      buildContextBlock(snapshot),
    ].join('\n');
  }

  async generateReply({ userText, snapshot, turns = [] }) {
    const contents = [];
    for (const turn of turns) {
      contents.push({
        role: turn.role === 'assistant' ? 'model' : 'user',
        parts: [{ text: turn.text }],
      });
    }
    contents.push({ role: 'user', parts: [{ text: userText }] });

    const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(
      this.model,
    )}:generateContent?key=${encodeURIComponent(this.apiKey)}`;

    let res;
    try {
      res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          systemInstruction: { parts: [{ text: this.systemPrompt(snapshot) }] },
          contents,
          tools: [{ google_search: {} }],
          generationConfig: { temperature: 0.7, maxOutputTokens: 1024 },
        }),
      });
    } catch (err) {
      throw new Error(`Network error reaching Gemini: ${err.message}`);
    }

    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (body.error && body.error.message) detail = body.error.message;
      } catch {
        /* ignore parse error */
      }
      if (res.status === 400 || res.status === 403) {
        throw new Error(`Gemini rejected the request (check your API key): ${detail}`);
      }
      throw new Error(`Gemini error: ${detail}`);
    }

    const data = await res.json();
    const candidate = (data.candidates && data.candidates[0]) || {};
    const parts = (candidate.content && candidate.content.parts) || [];
    const reply = parts
      .map((p) => p.text || '')
      .join('')
      .trim();

    const sources = extractSources(candidate.groundingMetadata);

    return {
      reply: reply || "I didn't catch a response there — mind trying again?",
      sources,
    };
  }
}

function extractSources(groundingMetadata) {
  if (!groundingMetadata) return [];
  const chunks = groundingMetadata.groundingChunks || [];
  const seen = new Set();
  const sources = [];
  for (const chunk of chunks) {
    const web = chunk.web || chunk.retrievedContext;
    if (web && web.uri && !seen.has(web.uri)) {
      seen.add(web.uri);
      sources.push({ title: web.title || web.uri, uri: web.uri });
    }
  }
  return sources.slice(0, 6);
}
