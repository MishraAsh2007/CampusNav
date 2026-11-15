import { useCallback, useEffect, useRef, useState } from 'react';
import { isVoiceSupported, speak as voiceSpeak, stop as voiceStop } from '../../services/voiceEngine';

/** React wrapper around the shared voice engine (deep voice, numbering stripped before speaking). */
export function useSpeech() {
  const supported = isVoiceSupported();
  const [speaking, setSpeaking] = useState(false);
  const token = useRef(0);

  const stop = useCallback(() => {
    voiceStop();
    setSpeaking(false);
  }, []);

  const speak = useCallback((text, opts = {}) => {
    const id = ++token.current;
    voiceSpeak(text, {
      ...opts,
      onStart: () => setSpeaking(true),
      onEnd: () => id === token.current && setSpeaking(false)
    });
  }, []);

  useEffect(() => stop, [stop]);
  return { supported, speaking, speak, stop };
}
