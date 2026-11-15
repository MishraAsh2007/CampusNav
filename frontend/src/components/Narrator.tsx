import { useEffect, useState } from 'react';
import { Pause, Sparkles, Volume2 } from 'lucide-react';
import type { RouteResponse, UserPreferences } from '../types';
import { generateTemplateNarration, getGeminiEnhancedNarration } from '../services/geminiService';
import { audioService } from '../services/audioService';

interface Props {
  route: RouteResponse | null;
  originName: string;
  destinationName: string;
  prefs: UserPreferences;
}

/** Plain-language summary. Template text is instant; Gemini replaces it only if it answers within 2.5 s. */
export function Narrator({ route, originName, destinationName, prefs }: Props) {
  const [text, setText] = useState('');
  const [source, setSource] = useState<'gemini' | 'template'>('template');
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    if (!route) return;
    let live = true;
    setText(generateTemplateNarration(route, originName, destinationName, prefs));
    setSource('template');
    // Debounce so slider drags do not fire a request per tick
    const t = setTimeout(() => {
      getGeminiEnhancedNarration(route, originName, destinationName, prefs).then((r) => {
        if (live && r.source === 'gemini') {
          setText(r.narration);
          setSource('gemini');
        }
      });
    }, 600);
    return () => {
      live = false;
      clearTimeout(t);
      audioService.stop();
      setSpeaking(false);
    };
  }, [route, originName, destinationName, prefs]);

  if (!route || !text) return null;

  const toggle = () => {
    if (speaking) {
      audioService.stop();
      setSpeaking(false);
      return;
    }
    const steps = route.steps.map((s) => s.instruction).join('. ');
    setSpeaking(true);
    audioService.speak(`${text} Directions: ${steps}.`, () => setSpeaking(false));
  };

  return (
    <section className="rounded-3xl bg-gradient-to-br from-lift-soft/70 to-sky-soft/60 p-4" aria-live="polite">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[12px] font-medium text-lift-ink">
          <Sparkles className="h-3.5 w-3.5" />
          {source === 'gemini' ? 'Summary by Gemini' : 'Summary'}
        </span>
        <button onClick={toggle} className="btn !px-2.5 !py-1 text-[12px] bg-white/80 text-ink hover:bg-white" aria-pressed={speaking}>
          {speaking ? <Pause className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
          {speaking ? 'Stop' : 'Read aloud'}
        </button>
      </div>
      <p className="text-[14px] leading-relaxed text-ink-2">{text}</p>
    </section>
  );
}
