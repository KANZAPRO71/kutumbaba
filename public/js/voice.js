// Voice layer: speech-to-text and text-to-speech.
//
// - On the native Android app (Capacitor), it uses the reliable native engines
//   via the @capacitor-community/speech-recognition and text-to-speech plugins.
// - On the web, it falls back to the browser Web Speech API.
// - If neither is available, the app stays fully usable via typing.
//
// The exported API is identical across platforms so the app controller doesn't
// need to know where it's running.

const WebSR = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;

function cap() {
  return globalThis.Capacitor;
}
function isNative() {
  const c = cap();
  return Boolean(c && c.isNativePlatform && c.isNativePlatform());
}
function plugin(name) {
  const c = cap();
  return c && c.Plugins ? c.Plugins[name] : null;
}

export function recognitionSupported() {
  if (isNative()) return Boolean(plugin('SpeechRecognition'));
  return Boolean(WebSR);
}

export function synthesisSupported() {
  if (isNative()) return Boolean(plugin('TextToSpeech'));
  return typeof globalThis.speechSynthesis !== 'undefined';
}

function cleanForSpeech(text) {
  return text
    .replace(/[#*_`>]/g, '')
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/* ---------------- Speech recognition ---------------- */

export function createRecognizer(handlers = {}) {
  if (isNative() && plugin('SpeechRecognition')) {
    return createNativeRecognizer(handlers);
  }
  return createWebRecognizer(handlers);
}

function createNativeRecognizer({ onResult, onStart, onEnd, onError } = {}) {
  const SR = plugin('SpeechRecognition');
  const api = { supported: true, listening: false };
  let lastText = '';
  let listener = null;

  api.start = async () => {
    try {
      await SR.requestPermissions();
      lastText = '';
      listener = await SR.addListener('partialResults', (data) => {
        const t = (data && data.matches && data.matches[0]) || '';
        if (t) {
          lastText = t;
          onResult && onResult({ interim: t, final: '' });
        }
      });
      api.listening = true;
      onStart && onStart();
      // On some devices start() resolves with the final matches at the end.
      SR.start({
        language: 'en-US',
        maxResults: 1,
        partialResults: true,
        popup: false,
      })
        .then((res) => {
          if (res && res.matches && res.matches[0]) lastText = res.matches[0];
        })
        .catch(() => {
          /* stop() path reports completion */
        });
    } catch (e) {
      api.listening = false;
      onError && onError((e && e.message) || 'speech-error');
    }
  };

  api.stop = async () => {
    try {
      await SR.stop();
    } catch {
      /* ignore */
    }
    if (listener && listener.remove) {
      try {
        await listener.remove();
      } catch {
        /* ignore */
      }
    }
    api.listening = false;
    if (lastText) onResult && onResult({ interim: '', final: lastText });
    onEnd && onEnd();
  };

  return api;
}

function createWebRecognizer({ onResult, onStart, onEnd, onError } = {}) {
  if (!WebSR) {
    return { supported: false, start() {}, stop() {}, listening: false };
  }

  const recognition = new WebSR();
  recognition.lang = 'en-US';
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;

  const api = { supported: true, listening: false };

  recognition.onstart = () => {
    api.listening = true;
    onStart && onStart();
  };
  recognition.onerror = (e) => {
    api.listening = false;
    onError && onError(e.error || 'speech-error');
  };
  recognition.onend = () => {
    api.listening = false;
    onEnd && onEnd();
  };
  recognition.onresult = (event) => {
    let interim = '';
    let final = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (event.results[i].isFinal) final += transcript;
      else interim += transcript;
    }
    onResult && onResult({ interim, final });
  };

  api.start = () => {
    try {
      recognition.start();
    } catch {
      /* already started */
    }
  };
  api.stop = () => {
    try {
      recognition.stop();
    } catch {
      /* ignore */
    }
  };
  return api;
}

/* ---------------- Text to speech ---------------- */

export function speak(text, { enabled = true, onStart, onEnd } = {}) {
  if (!enabled || !text) {
    onEnd && onEnd();
    return;
  }
  const spoken = cleanForSpeech(text);
  if (!spoken) {
    onEnd && onEnd();
    return;
  }

  if (isNative() && plugin('TextToSpeech')) {
    onStart && onStart();
    plugin('TextToSpeech')
      .speak({ text: spoken, lang: 'en-US', rate: 1.0, pitch: 1.0, volume: 1.0 })
      .then(() => onEnd && onEnd())
      .catch(() => onEnd && onEnd());
    return;
  }

  if (!synthesisSupported()) {
    onEnd && onEnd();
    return;
  }
  try {
    speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(spoken);
    utter.lang = 'en-US';
    utter.rate = 1.02;
    utter.pitch = 1.0;
    utter.onstart = () => onStart && onStart();
    utter.onend = () => onEnd && onEnd();
    utter.onerror = () => onEnd && onEnd();
    speechSynthesis.speak(utter);
  } catch {
    onEnd && onEnd();
  }
}

export function stopSpeaking() {
  if (isNative() && plugin('TextToSpeech')) {
    try {
      plugin('TextToSpeech').stop();
    } catch {
      /* ignore */
    }
    return;
  }
  if (typeof globalThis.speechSynthesis !== 'undefined') {
    try {
      speechSynthesis.cancel();
    } catch {
      /* ignore */
    }
  }
}
