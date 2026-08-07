// Voice layer: speech-to-text (SpeechRecognition) and text-to-speech
// (speechSynthesis). Both degrade gracefully when unavailable so the app is
// always usable via typing.

const SpeechRecognitionCtor =
  globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;

export function recognitionSupported() {
  return Boolean(SpeechRecognitionCtor);
}

export function synthesisSupported() {
  return typeof globalThis.speechSynthesis !== 'undefined';
}

export function createRecognizer({ onResult, onStart, onEnd, onError } = {}) {
  if (!SpeechRecognitionCtor) {
    return { supported: false, start() {}, stop() {}, listening: false };
  }

  const recognition = new SpeechRecognitionCtor();
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
      /* start() throws if already started — safe to ignore */
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

let currentUtterance = null;

export function speak(text, { enabled = true, onStart, onEnd } = {}) {
  if (!enabled || !synthesisSupported() || !text) {
    onEnd && onEnd();
    return;
  }
  // Strip emoji/markdown-ish characters so TTS sounds clean.
  const spoken = text
    .replace(/[#*_`>]/g, '')
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
    .replace(/\s+/g, ' ')
    .trim();

  try {
    speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(spoken);
    utter.lang = 'en-US';
    utter.rate = 1.02;
    utter.pitch = 1.0;
    utter.onstart = () => onStart && onStart();
    utter.onend = () => onEnd && onEnd();
    utter.onerror = () => onEnd && onEnd();
    currentUtterance = utter;
    speechSynthesis.speak(utter);
  } catch {
    onEnd && onEnd();
  }
}

export function stopSpeaking() {
  if (synthesisSupported()) {
    try {
      speechSynthesis.cancel();
    } catch {
      /* ignore */
    }
  }
  currentUtterance = null;
}
