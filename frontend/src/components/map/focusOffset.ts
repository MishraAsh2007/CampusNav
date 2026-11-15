/** Center a selected step in the map area left visible by the directions panels. */
export function focusOffset(): [number, number] {
  const width = window.innerWidth, height = window.innerHeight;
  const wide = width >= 1024;
  const trip = document.querySelector('[aria-label="Trip planner"]')?.getBoundingClientRect();
  const directions = document.querySelector('[aria-label="Current route directions"]')?.getBoundingClientRect();
  const left = wide && trip?.width ? trip.right + 20 : 24;
  const right = wide && directions?.width ? directions.left - 20 : width - 24;
  const top = Math.min(148, height / 3);
  const bottom = !wide && trip?.height ? Math.max(top + 40, trip.top - 20) : height - 48;
  return [(left + Math.max(left, right)) / 2 - width / 2, (top + bottom) / 2 - height / 2];
}
