/** Cache API data for this tab's browser session. Storage may be disabled or full. */
export function readSessionCache<T>(
  key: string, isItem: (value: unknown) => value is T,
): T[] | null {
  try {
    const stored = sessionStorage.getItem(key);
    if (stored === null) return null;
    const data: unknown = JSON.parse(stored);
    return Array.isArray(data) && data.every(isItem) ? data : null;
  } catch {
    return null;
  }
}

export function writeSessionCache<T>(key: string, data: T[]): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(data));
  } catch {
    // The in-memory data remains usable if the browser cannot cache it.
  }
}
