/**
 * CampusNav voice engine: one natural voice for every spoken direction (indoor and outdoor).
 * Built on window.speechSynthesis; safe to import where it doesn't exist (calls become no-ops).
 *
 *   speak('3. Turn left down the corridor')       -> says "Turn left down the corridor."
 *   speak('Recalculating route.', { priority: true }) -> interrupts, and the next normal line waits for it
 *
 * Voice: Google's own voice when the browser has it (desktop Chrome: "Google US English", the same
 * voice family Google Maps uses); otherwise the device's default voice, untouched. On Android Chrome
 * the default is the Google text-to-speech engine, the one Google Maps speaks with; on iPhone it is
 * the voice set in Settings > Accessibility > Spoken Content.
 */

// Normal pitch and speed: what Google Maps sounds like
export const VOICE_SETTINGS = { pitch: 1, rate: 1, volume: 1 };

// Google voices, best first. If none exist, no voice is set and the device default is used.
const PREFERRED: RegExp[] = [/^google us english$/i, /^google uk english female$/i, /^google english/i];

const synth: SpeechSynthesis | null = typeof window !== 'undefined' && 'speechSynthesis' in window ? window.speechSynthesis : null;

let cachedVoice: SpeechSynthesisVoice | null | undefined;
let muted = false;
let priorityActive = false;
let pending: { text: string; opts: SpeakOptions } | null = null;

export function isVoiceSupported(): boolean {
  return !!synth;
}

/** A Google voice if the browser has one, else null (= the device's default voice). Cached. */
export function pickVoice(): SpeechSynthesisVoice | null {
  if (!synth) return null;
  if (cachedVoice !== undefined) return cachedVoice;
  const voices = synth.getVoices();
  if (!voices.length) return null; // not loaded yet: use the default for now, try again next time
  for (const re of PREFERRED) {
    const v = voices.find((x) => re.test(x.name));
    if (v) return (cachedVoice = v);
  }
  cachedVoice = null;
  return cachedVoice;
}

if (synth) {
  // Chrome loads voices asynchronously
  synth.addEventListener?.('voiceschanged', () => {
    cachedVoice = undefined;
    pickVoice();
  });
}

/**
 * Strip on-screen numbering so only the action is spoken:
 *   "3. Turn left down the corridor"  -> "Turn left down the corridor"
 *   "Step 3. Go straight 40 feet."     -> "Go straight 40 feet."
 *   "Step 3 of 8: Take the elevator"   -> "Take the elevator"
 * Room numbers ("S331"), distances ("40 feet") and decimals ("4.5%") are left alone.
 */
export function cleanForSpeech(text: string): string {
  return String(text ?? '')
    .replace(/\bstep\s*\d+\s*(?:of\s*\d+)?\s*[.:)\-–—]?\s*/gi, '') // "Step 3.", "Step 3 of 8:"
    .replace(/(^|[\n.!?]\s+)\d+\s*[.):\]]\s+/g, '$1') // "3. ", "3) " at the start of a line or sentence
    .replace(/^\s*\d+\s*[.):\]]\s*/, '') // "3." with nothing after the dot but the text
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '') // emoji icons from the UI
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export interface SpeakOptions {
  /** Interrupt anything playing; normal lines spoken during it wait until it finishes. */
  priority?: boolean;
  onStart?: () => void;
  onEnd?: () => void;
}

/**
 * Chrome's Google voices stop after ~15 s of one utterance, so long text (the outdoor summary) is
 * spoken a few sentences at a time. Short directions stay one utterance.
 */
function chunks(text: string, max = 160): string[] {
  const sentences = text.match(/[^.!?]+[.!?]*\s*/g) ?? [text];
  const out: string[] = [];
  let cur = '';
  for (const s of sentences) {
    if (cur && (cur + s).length > max) {
      out.push(cur.trim());
      cur = '';
    }
    cur += s;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

function utter(text: string, opts: SpeakOptions) {
  if (!synth) return;
  const parts = chunks(text);
  const v = pickVoice();
  parts.forEach((part, i) => {
    const u = new SpeechSynthesisUtterance(part);
    u.pitch = VOICE_SETTINGS.pitch;
    u.rate = VOICE_SETTINGS.rate;
    u.volume = VOICE_SETTINGS.volume;
    if (v) {
      u.voice = v;
      u.lang = v.lang;
    } // else: leave voice and language unset so the device default speaks
    if (i === 0) u.onstart = () => opts.onStart?.();
    if (i === parts.length - 1) {
      const done = () => {
        if (opts.priority) {
          priorityActive = false;
          const next = pending;
          pending = null;
          if (next) utter(next.text, next.opts);
        }
        opts.onEnd?.();
      };
      u.onend = done;
      u.onerror = done;
    }
    synth.speak(u); // queued in order by the browser
  });
}

/** Speak a direction. Always cleans the text first. Returns false if nothing was spoken. */
export function speak(text: string, opts: SpeakOptions = {}): boolean {
  if (!synth || muted) return false;
  const clean = cleanForSpeech(text);
  if (!clean) return false;
  if (opts.priority) {
    pending = null;
    synth.cancel();
    priorityActive = true;
    utter(clean, opts);
    return true;
  }
  if (priorityActive) {
    // e.g. the new first step arriving while "Recalculating route." is still playing
    pending = { text: clean, opts };
    return true;
  }
  synth.cancel(); // the newest direction wins; never read out a stale queue
  utter(clean, opts);
  return true;
}

export function stop(): void {
  pending = null;
  priorityActive = false;
  synth?.cancel();
}

/** Mute every spoken line (the indoor "Voice off" button). */
export function setVoiceMuted(value: boolean): void {
  muted = value;
  if (value) stop();
}

export function isSpeaking(): boolean {
  return !!synth?.speaking;
}
