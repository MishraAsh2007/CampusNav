/**
 * Outdoor "Read aloud". Uses the shared voice engine so indoor and outdoor directions sound the same.
 */
import { speak as voiceSpeak, stop as voiceStop } from './voiceEngine';

class AudioService {
  private speaking = false;

  public speak(text: string, onEnd?: () => void): void {
    voiceSpeak(text, {
      onStart: () => {
        this.speaking = true;
      },
      onEnd: () => {
        this.speaking = false;
        onEnd?.();
      }
    });
  }

  public stop(): void {
    voiceStop();
    this.speaking = false;
  }

  public getSpeaking(): boolean {
    return this.speaking;
  }
}

export const audioService = new AudioService();
