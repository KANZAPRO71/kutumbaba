# Papua AI (Beta)

Teman ngobrol suara di Android — voice-first, logat Melayu Papua urban, BYOK Gemini.

**Ko buka app → tekan → cerita aja.**

---

## Download APK (Android)

[![Download latest release](https://img.shields.io/github/v/release/KANZAPRO71/kutumbaba?label=Download%20APK&style=for-the-badge)](https://github.com/KANZAPRO71/kutumbaba/releases/latest)

**Link langsung:** https://github.com/KANZAPRO71/kutumbaba/releases/latest

> Versi beta — sideload (belum Play Store). Butuh Android 7+ (API 24), koneksi internet, dan Gemini API key milik sendiri.

### Cara install

1. Tap **Download APK** di [halaman Releases](https://github.com/KANZAPRO71/kutumbaba/releases/latest)
2. Izinkan **Install from unknown sources** jika diminta
3. Install → buka **Papua AI**
4. Masukkan **Gemini API key** ([Google AI Studio](https://aistudio.google.com) — ada tier gratis)
5. Izinkan **mikrofon** → tekan tombol ngobrol → cerita aja

API key bisa diganti kapan saja lewat tombol **⚙ Pengaturan** di pojok kanan atas.

---

## Fitur utama

- **Voice-first** — pengalaman utama suara, bukan chat teks panjang
- **Logat Melayu Papua urban** — natural, ringan, dekat
- **Local-first** — backend Python jalan di HP (Chaquopy), bukan server developer
- **BYOK** — key Gemini milik user, disimpan lokal di perangkat
- **Identitas Papua** — UI dengan nuansa cenderawasih

---

## Privasi & BYOK

- API key **tidak** disimpan di server developer — hanya di HP user (EncryptedSharedPreferences)
- Saat ngobrol, audio/teks dikirim ke **Gemini API** sesuai key user sendiri
- Session & memori disimpan lokal di perangkat

---

## Build dari source (developer)

```bat
cd android
gradlew.bat assembleDebug
```

APK: `android/app/build/outputs/apk/debug/app-debug.apk`

Detail arsitektur: [docs/BYOK_ANDROID.md](docs/BYOK_ANDROID.md)

---

## Feedback

Versi beta — bug report & saran UX sangat welcome. Buka [Issues](https://github.com/KANZAPRO71/kutumbaba/issues) atau DM di LinkedIn.

---

**Versi saat ini:** 2.9.3-barge-fix (beta)
