/** Presentation only: API distances and routing calculations remain in meters. */
export function formatDistance(metres: number): string {
  const feet = metres * 3.28084;
  return Math.abs(feet) >= 5280 ? `${(feet / 5280).toFixed(1)} mi` : `${Math.round(feet)} ft`;
}

export function displayInstruction(text: string): string {
  return text.replace(/\b(\d+(?:\.\d+)?)\s*(?:m|meters|metres)\b/g,
    (_, value) => formatDistance(Number(value)));
}
