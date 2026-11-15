import type { ComponentType } from 'react';

declare const IndoorStepPanel: ComponentType<{
  steps: {id: string; text: string; kind: string; distanceM?: number}[];
  active: number;
  onGo: (step: number) => void;
  onDone: () => void;
  autoSpeak?: boolean;
  className?: string;
}>;

export default IndoorStepPanel;
