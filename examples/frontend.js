// Role 2 integration example. Role 4 owns GET /closures and POST /reports.
export async function calculateRoute({ start, end, maxGrade = 5, noStairs = true }) {
  const closureResponse = await fetch("http://localhost:8001/closures");
  if (!closureResponse.ok) throw new Error("Could not load current closures");
  const closures = await closureResponse.json(); // Plain array, not { closures: [...] }.
  const response = await fetch("http://localhost:8000/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, end, max_grade: maxGrade, no_stairs: noStairs, closures }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail?.message ?? "Could not calculate route");
  // Leaflet: L.geoJSON(body).addTo(map).
  // UI: body.properties.total_distance, .max_grade, .warnings, .directions.
  // After a report succeeds, call this function again to fetch fresh closures and reroute.
  return body;
}
