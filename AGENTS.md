# AGENTS.md

## Cursor Cloud specific instructions

### Product
**Studio** (`kutumbaba-studio`) is a client-only Vite + React demo: Indonesian AI app builder UI with mock prompt → preview generation (toko online / project dashboard). No backend, database, or API keys required.

### Commands
See `README.md` / `package.json` scripts: `npm run dev`, `npm run lint`, `npm test`, `npm run build`.

### Runtime notes
- Dev server binds `0.0.0.0:5173` (configured in `vite.config.ts`) so it is reachable from the cloud desktop/browser tooling.
- App generation is deterministic template matching in `src/lib/studio.ts` (keyword-based), not a live LLM. Do not expect OpenAI/network calls for the core demo flow.
- Hello-world verification path: open the app → **Mulai di Studio** → send `Buat toko online sederhana dengan daftar produk` → **Add to Cart** on a product (or **Add Produk**).
- Alternate persona path: prompt `Bangun aplikasi manajemen proyek untuk kuliah` → **To Do List** (complete task) → **Add Modul**.
- Optional automation (not part of startup): `npx playwright@1.55.0 install chromium` then `node scripts/demo-hello-world.mjs`.
